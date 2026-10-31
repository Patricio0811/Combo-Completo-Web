import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Avg, Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from . import services
from .models import (
    AlertaStock, Comanda, Insumo, Pago, Pedido, Producto, RegistroAuditoria, CierreCaja,
)
from .permisos import rol_requerido
from .services import ErrorNegocio

INICIO = {"garzon": "garzon", "cocina": "cocina", "cajero": "caja", "admin": "reportes"}


def _decimal(valor, defecto=Decimal(0)):
    try:
        return Decimal(str(valor).strip() or defecto)
    except InvalidOperation:
        raise ErrorNegocio("Ingresa un número válido.")


def inicio(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect(INICIO.get(request.user.rol, "garzon"))


# ---------- Garzón (HU01) ----------
@rol_requerido("garzon")
def garzon(request):
    productos = [{"id": p.pk, "nombre": p.nombre, "precio": int(p.precio)}
                 for p in Producto.objects.filter(activo=True)]
    return render(request, "sistema/garzon.html", {"productos": productos})


@rol_requerido("garzon", api=True)
@require_POST
def api_pedido_crear(request):
    try:
        d = json.loads(request.body)
        pedido = services.crear_pedido(
            request.user, d.get("canal"), d.get("datos", {}), d.get("items", []), d.get("observaciones", ""))
    except ErrorNegocio as e:
        return JsonResponse({"error": str(e)}, status=400)
    except (ValueError, KeyError, TypeError, InvalidOperation):
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


@rol_requerido("cocina", api=True)
def api_comandas(request):
    """Ordenadas por hora de llegada. La pantalla consulta cada 2 s (RNF03: menos de 4 s)."""
    comandas = (Comanda.objects.exclude(estado="lista").exclude(pedido__estado="anulado")
                .select_related("pedido", "pedido__pedidolocal", "pedido__pedidoretiro",
                                "pedido__pedidodomicilio__cliente")
                .prefetch_related("pedido__detalles__producto").order_by("hora_llegada"))
    ahora = timezone.now()
    data = []
    for c in comandas:
        p = c.pedido
        data.append({
            "id": c.pk, "pedido": p.pk, "canal": p.canal, "ref": p.referencia,
            "estado": c.estado, "obs": p.observaciones,
            "segundos": int((ahora - c.hora_llegada).total_seconds()),
            "hora": timezone.localtime(c.hora_llegada).strftime("%H:%M"),
            "items": [{"n": d.producto.nombre, "c": d.cantidad} for d in p.detalles.all()],
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
                AlertaStock.objects.filter(pk=request.POST.get("alerta")).update(atendida=True)
            else:
                insumo = get_object_or_404(Insumo, pk=request.POST.get("insumo"))
                if accion == "entrada":
                    cant = _decimal(request.POST.get("cantidad"))
                    if cant <= 0:
                        raise ErrorNegocio("La cantidad debe ser mayor que cero.")
                    services.registrar_entrada(insumo, cant, request.user)
                    messages.success(request, f"Entrada registrada: {insumo.nombre}.")
                elif accion == "ajuste":
                    services.ajustar_stock(insumo, _decimal(request.POST.get("nuevo")),
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
                pedido = get_object_or_404(Pedido, pk=request.POST.get("pedido"))
                services.registrar_pago(pedido, request.POST.get("metodo"),
                                        _decimal(request.POST.get("monto")), request.user)
                messages.success(request, f"Pago registrado en el pedido #{pedido.pk}.")
            elif accion == "cierre":
                cierre = services.cerrar_caja(request.user, {m: request.POST.get(f"contado_{m}")
                                                              for m, _ in Pago.Metodo.choices})
                messages.success(request, f"Caja cerrada. Diferencia: ${cierre.diferencia:,.0f}".replace(",", "."))
            elif accion == "anular" and request.user.tiene_rol("admin"):
                services.anular_pedido(get_object_or_404(Pedido, pk=request.POST.get("pedido")),
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
    return render(request, "sistema/caja.html", {
        "pendientes": pendientes, "metodos": Pago.Metodo.choices,
        "esperado": [(m, n, esperado[m]) for m, n in Pago.Metodo.choices],
        "total_esperado": sum(esperado.values()), "cierres": CierreCaja.objects.all()[:5],
    })


# ---------- Reportes (HU05) ----------
@rol_requerido("admin")
def reportes(request):
    hoy = timezone.localdate()
    desde = parse_date(request.GET.get("desde", "")) or hoy - timedelta(days=6)
    hasta = parse_date(request.GET.get("hasta", "")) or hoy
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
    por_dia = (qs.values("fecha_hora__date").annotate(n=Count("id"), t=Sum("total")).order_by("fecha_hora__date"))
    total = qs.aggregate(t=Sum("total"))["t"] or 0
    return render(request, "sistema/reportes.html", {
        "desde": desde, "hasta": hasta, "canal": canal, "por_canal": por_canal,
        "por_dia": por_dia, "total": total, "n": qs.count(),
        "ticket_promedio": agg["ticket_promedio"] or 0, "por_metodo": por_metodo,
        "max_dia": max((d["t"] for d in por_dia), default=0) or 1,
        "top": (qs.values("detalles__producto__nombre").annotate(c=Sum("detalles__cantidad"))
                .order_by("-c")[:5]),
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


#COMENTARIO DE PRUEBA
