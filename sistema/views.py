import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Avg, Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek, TruncYear
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from . import respaldo, services
from .models import (
    Agregado, AlertaStock, Comanda, Insumo, Pago, Pedido, PedidoDomicilio, Producto, RegistroAuditoria, CierreCaja,
)
from .permisos import rol_requerido
from .services import ErrorNegocio

INICIO = {"garzon": "garzon", "cocina": "cocina", "cajero": "caja", "admin": "reportes"}


def _pk(valor):
    """Id recibido desde un formulario: si no es un entero válido responde 404 (y no un error 500)."""
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        raise Http404("Identificador no válido")
    if not 1 <= n <= 2_147_483_647:
        raise Http404("Identificador no válido")
    return n


def inicio(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect(INICIO.get(request.user.rol, "garzon"))


# ---------- Garzón (HU01) ----------
@rol_requerido("garzon")
def garzon(request):
    productos = [{"id": p.pk, "nombre": p.nombre, "precio": int(p.precio)}
                 for p in Producto.objects.filter(activo=True)]
    agregados = [{"id": a.pk, "nombre": a.nombre, "precio": int(a.precio)}
                 for a in Agregado.objects.filter(activo=True)]
    return render(request, "sistema/garzon.html", {"productos": productos, "agregados": agregados})


@rol_requerido("garzon", api=True)
@require_POST
def api_pedido_crear(request):
    """El local vende por Retiro o Domicilio. El canal debe elegirse de forma explícita; 'local' ya no se acepta."""
    try:
        d = json.loads(request.body)
        canal = d.get("canal")
        if canal not in ("retiro", "domicilio"):
            raise ErrorNegocio("Elige el canal de venta: Retiro o Domicilio.")
        pedido = services.crear_pedido(
            request.user, canal, d.get("datos", {}), d.get("items", []), d.get("observaciones", ""),
            d.get("agregados", []))
    except ErrorNegocio as e:
        return JsonResponse({"error": str(e)}, status=400)
    except (ValueError, KeyError, TypeError, InvalidOperation, AttributeError):
        return JsonResponse({"error": "Datos del pedido no válidos."}, status=400)
    return JsonResponse({"id": pedido.pk, "total": int(pedido.total), "canal": pedido.canal})


@rol_requerido("garzon", api=True)
def api_listos(request):
    pedidos = Pedido.objects.filter(estado="listo", usuario=request.user)
    return JsonResponse({"listos": [{"id": p.pk, "canal": p.canal, "ref": p.referencia} for p in pedidos]})


@rol_requerido("garzon", api=True)
@require_POST
def api_entregar(request, pk):
    n = Pedido.objects.filter(pk=pk, estado="listo", usuario=request.user).update(estado="entregado")
    return JsonResponse({"ok": bool(n)})


# ---------- Cocina (HU02) ----------
@rol_requerido("cocina")
def cocina(request):
    return render(request, "sistema/cocina.html")


def _cantidad(x):
    """Decimal sin ceros sobrantes: 0.050 -> '0.05', 2.000 -> '2'."""
    return format(x.normalize(), "f")


def _item_comanda(d):
    """Producto de la comanda con su detalle y los insumos que consume (para la vista ampliada de cocina)."""
    return {
        "n": d.producto.nombre, "c": d.cantidad, "d": d.producto.detalle,
        "ins": [{"n": r.insumo.nombre, "c": _cantidad(r.cantidad_por_unidad * d.cantidad), "u": r.insumo.unidad}
                for r in d.producto.recetas.all()],
    }


def _item_agregado(a):
    """Los agregados salen en la comanda como un ítem más, con el prefijo «+», y con los insumos que consumen."""
    return {
        "n": f"+ {a.agregado.nombre}", "c": a.cantidad, "d": "",
        "ins": [{"n": r.insumo.nombre, "c": _cantidad(r.cantidad_por_unidad * a.cantidad), "u": r.insumo.unidad}
                for r in a.agregado.recetas.all()],
    }


@rol_requerido("cocina", api=True)
def api_comandas(request):
    """Ordenadas por hora de llegada. La pantalla consulta cada 2 s (RNF03: menos de 4 s)."""
    comandas = (Comanda.objects.exclude(estado="lista").exclude(pedido__estado="anulado")
                .select_related("pedido", "pedido__pedidolocal", "pedido__pedidoretiro",
                                "pedido__pedidodomicilio__cliente")
                .prefetch_related("pedido__detalles__producto__recetas__insumo",
                                  "pedido__agregados__agregado__recetas__insumo").order_by("hora_llegada"))
    ahora = timezone.now()
    data = []
    for c in comandas:
        p = c.pedido
        data.append({
            "id": c.pk, "pedido": p.pk, "canal": p.canal, "ref": p.referencia,
            "estado": c.estado, "obs": p.observaciones,
            "segundos": int((ahora - c.hora_llegada).total_seconds()),
            "hora": timezone.localtime(c.hora_llegada).strftime("%H:%M"),
            "items": [_item_comanda(d) for d in p.detalles.all()] + [_item_agregado(a) for a in p.agregados.all()],
        })
    return JsonResponse({"comandas": data})


@rol_requerido("cocina", api=True)
@require_POST
def api_comanda_estado(request, pk):
    comanda = get_object_or_404(Comanda, pk=pk)
    try:
        services.cambiar_estado_comanda(comanda, json.loads(request.body).get("estado"))
    except ErrorNegocio as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"ok": True})


# ---------- Inventario (HU03, HU04) ----------
@rol_requerido("admin")
def inventario(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "atender":
                AlertaStock.objects.filter(pk=_pk(request.POST.get("alerta"))).update(atendida=True)
            else:
                insumo = get_object_or_404(Insumo, pk=_pk(request.POST.get("insumo")))
                if accion == "entrada":
                    cant = services.leer_decimal(request.POST.get("cantidad"), "Cantidad")
                    if cant <= 0:
                        raise ErrorNegocio("La cantidad debe ser mayor que cero.")
                    services.registrar_entrada(insumo, cant, request.user)
                    messages.success(request, f"Entrada registrada: {insumo.nombre}.")
                elif accion == "ajuste":
                    services.ajustar_stock(insumo, services.leer_decimal(request.POST.get("nuevo"), "Nuevo stock"),
                                           request.user, request.POST.get("motivo", ""))
                    messages.success(request, f"Stock de {insumo.nombre} ajustado y registrado en auditoría.")
        except ErrorNegocio as e:
            messages.error(request, str(e))
        return redirect("inventario")
    return render(request, "sistema/inventario.html", {
        "insumos": Insumo.objects.all(),
        "alertas": AlertaStock.objects.filter(atendida=False).select_related("insumo"),
    })


# ---------- Caja (HU06) ----------
@rol_requerido("cajero")
def caja(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "pago":
                pedido = get_object_or_404(Pedido, pk=_pk(request.POST.get("pedido")))
                services.registrar_pago(pedido, request.POST.get("metodo"),
                                        services.leer_entero(request.POST.get("monto"), "Monto"), request.user)
                messages.success(request, f"Pago registrado en el pedido #{pedido.pk}.")
            elif accion == "cierre":
                cierre = services.cerrar_caja(request.user, {m: request.POST.get(f"contado_{m}")
                                                              for m, _ in Pago.Metodo.choices})
                messages.success(request, f"Caja cerrada. Diferencia: ${cierre.diferencia:,.0f}".replace(",", "."))
            elif accion == "anular" and request.user.tiene_rol("admin"):
                services.anular_pedido(get_object_or_404(Pedido, pk=_pk(request.POST.get("pedido"))),
                                       request.user, request.POST.get("motivo", ""))
                messages.success(request, "Pedido anulado y registrado en auditoría.")
        except ErrorNegocio as e:
            messages.error(request, str(e))
        return redirect("caja")
    pendientes = (Pedido.objects.exclude(estado="anulado")
                  .filter(fecha_hora__gte=timezone.now() - timedelta(days=1))
                  .annotate(cobrado=Coalesce(Sum("pagos__monto"), Value(0), output_field=DecimalField()))
                  .filter(total__gt=F("cobrado"))
                  .select_related("pedidolocal", "pedidoretiro", "pedidodomicilio__cliente"))
    esperado = services.resumen_caja()
    pagados = (Pedido.objects.filter(fecha_pago__isnull=False).exclude(estado="anulado")
               .select_related("pedidolocal", "pedidoretiro", "pedidodomicilio__cliente").order_by("-fecha_pago")[:8])
    return render(request, "sistema/caja.html", {
        "pendientes": pendientes, "pagados": pagados, "metodos": Pago.Metodo.choices,
        "esperado": [(m, n, esperado[m]) for m, n in Pago.Metodo.choices],
        "total_esperado": sum(esperado.values()), "cierres": CierreCaja.objects.all()[:5],
    })


# ---------- Reportes (HU05) ----------
# Presets de período del reporte: clave -> (rango, agrupación por defecto)
PRESETS_REPORTE = (
    ("dia", "Hoy"), ("semana", "Semana"), ("mes", "Mes"), ("anio", "Año"),
)
AGRUPACIONES = (("dia", "Día"), ("semana", "Semana"), ("mes", "Mes"), ("anio", "Año"))
_TRUNC = {"dia": TruncDay, "semana": TruncWeek, "mes": TruncMonth, "anio": TruncYear}
_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _rango_preset(preset, hoy):
    """Fechas (desde, hasta) y agrupación sugerida de un preset; None si no existe."""
    if preset == "dia":
        return hoy, hoy, "dia"
    if preset == "semana":  # de lunes a hoy
        return hoy - timedelta(days=hoy.weekday()), hoy, "dia"
    if preset == "mes":
        return hoy.replace(day=1), hoy, "dia"
    if preset == "anio":
        return hoy.replace(month=1, day=1), hoy, "mes"
    return None


def _etiqueta_periodo(fecha, agrupar):
    if agrupar == "anio":
        return str(fecha.year)
    if agrupar == "mes":
        return f"{_MESES[fecha.month - 1]} {fecha.year}"
    if agrupar == "semana":
        fin = fecha + timedelta(days=6)
        return f"Sem. {fecha:%d/%m} – {fin:%d/%m}"
    return f"{_DIAS[fecha.weekday()]} {fecha:%d/%m}"


@rol_requerido("admin")
def reportes(request):
    hoy = timezone.localdate()
    preset = request.GET.get("periodo", "")
    rango = _rango_preset(preset, hoy)
    if rango:
        desde, hasta, agrupar_def = rango
    else:
        preset = ""
        desde = parse_date(request.GET.get("desde", "")) or hoy - timedelta(days=6)
        hasta = parse_date(request.GET.get("hasta", "")) or hoy
        agrupar_def = "dia"
    agrupar = request.GET.get("agrupar", "")
    if agrupar not in _TRUNC:
        agrupar = agrupar_def
    canal = request.GET.get("canal", "todos")
    qs = Pedido.objects.exclude(estado="anulado").filter(
        fecha_hora__date__gte=desde, fecha_hora__date__lte=hasta)
    filtro = {"local": "pedidolocal", "retiro": "pedidoretiro", "domicilio": "pedidodomicilio"}
    if canal in filtro:
        qs = qs.filter(**{f"{filtro[canal]}__isnull": False})
    agg = qs.aggregate(
        pedidos_local=Count("id", filter=Q(pedidolocal__isnull=False)),
        total_local=Sum("total", filter=Q(pedidolocal__isnull=False)),
        pedidos_retiro=Count("id", filter=Q(pedidoretiro__isnull=False)),
        total_retiro=Sum("total", filter=Q(pedidoretiro__isnull=False)),
        pedidos_domicilio=Count("id", filter=Q(pedidodomicilio__isnull=False)),
        total_domicilio=Sum("total", filter=Q(pedidodomicilio__isnull=False)),
        ticket_promedio=Avg("total"),
    )
    por_canal = [{"canal": n, "pedidos": agg[f"pedidos_{k}"], "total": agg[f"total_{k}"] or 0}
                 for n, k in (("Local", "local"), ("Retiro", "retiro"), ("Domicilio", "domicilio"))]
    por_metodo = (Pago.objects.filter(pedido__in=qs).values("metodo")
                  .annotate(n=Count("id"), t=Sum("monto")).order_by("-t"))
    nombres = dict(Pago.Metodo.choices)
    por_metodo = [{"metodo": nombres.get(m["metodo"], m["metodo"]), "n": m["n"], "t": m["t"]} for m in por_metodo]
    periodo = (qs.annotate(p=_TRUNC[agrupar]("fecha_hora")).values("p")
               .annotate(n=Count("id"), t=Sum("total")).order_by("p"))
    serie = [{"etiqueta": _etiqueta_periodo(timezone.localtime(d["p"]).date(), agrupar),
              "n": d["n"], "t": d["t"]} for d in periodo]
    total = qs.aggregate(t=Sum("total"))["t"] or 0
    top = list(qs.values("detalles__producto__nombre").annotate(c=Sum("detalles__cantidad"))
               .order_by("-c")[:8])
    top = [{"nombre": t["detalles__producto__nombre"], "c": t["c"]}
           for t in top if t["detalles__producto__nombre"]]
    # Datos para los gráficos (se entregan como JSON seguro con json_script)
    graficos = {
        "canal": [{"etiqueta": c["canal"], "valor": float(c["total"]), "extra": c["pedidos"]}
                  for c in por_canal if c["total"]],
        "metodo": [{"etiqueta": m["metodo"], "valor": float(m["t"] or 0), "extra": m["n"]}
                   for m in por_metodo if m["t"]],
        "top": [{"etiqueta": t["nombre"], "valor": float(t["c"] or 0)} for t in top],
    }
    return render(request, "sistema/reportes.html", {
        "desde": desde, "hasta": hasta, "canal": canal, "por_canal": por_canal,
        "serie": serie, "total": total, "n": qs.count(),
        "ticket_promedio": agg["ticket_promedio"] or 0, "por_metodo": por_metodo,
        "max_periodo": max((d["t"] for d in serie), default=0) or 1,
        "top": top, "graficos": graficos,
        "preset": preset, "presets": PRESETS_REPORTE,
        "agrupar": agrupar, "agrupaciones": AGRUPACIONES,
        "agrupar_nombre": dict(AGRUPACIONES)[agrupar],
    })


# ---------- Auditoría (CU09) ----------
@rol_requerido("admin")
def auditoria(request):
    accion = request.GET.get("accion", "")
    qs = RegistroAuditoria.objects.select_related("usuario")
    if accion:
        qs = qs.filter(accion=accion)
    return render(request, "sistema/auditoria.html", {
        "registros": qs[:200], "accion": accion,
        "acciones": RegistroAuditoria.objects.values_list("accion", flat=True).distinct(),
    })


# ---------- Domicilios: datos del cliente para quien despacha ----------
@rol_requerido("garzon", "cajero")
def domicilios(request):
    """Teléfono y dirección se guardan cifrados; solo los ven garzón, cajero y administrador (no cocina).
    Cada consulta queda en la auditoría (sin copiar los datos personales)."""
    desde = timezone.now() - timedelta(days=1)
    pedidos = (PedidoDomicilio.objects.exclude(estado="anulado").filter(fecha_hora__gte=desde)
               .select_related("cliente").prefetch_related("pagos").order_by("estado", "-fecha_hora"))
    services.auditar(request.user, "consulta_datos_domicilio", pedidos=len(pedidos))
    return render(request, "sistema/domicilios.html", {"pedidos": pedidos})


# ---------- Respaldo ----------
@rol_requerido("admin")
def respaldo_pagina(request):
    if request.method == "POST":
        contenido = respaldo.generar_respaldo()
        services.auditar(request.user, "respaldo_descargado", bytes=len(contenido))
        resp = HttpResponse(contenido, content_type="application/octet-stream")
        resp["Content-Disposition"] = f'attachment; filename="{respaldo.nombre_archivo()}"'
        return resp
    return render(request, "sistema/respaldo.html")
