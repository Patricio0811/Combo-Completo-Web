"""Reglas de negocio. Las vistas solo validan permisos y llaman a estas funciones."""
import re
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Agregado, AlertaStock, CierreCaja, Cliente, Comanda, DetalleAgregado, DetallePedido, Insumo,
    MovimientoInventario, Pago, Pedido, PedidoDomicilio, PedidoLocal,
    PedidoRetiro, Producto, Receta, RecetaAgregado, RegistroAuditoria,
)

CANALES = ("local", "retiro", "domicilio")
MAX_CANTIDAD = 99   # unidades máximas de un mismo producto en un pedido


class ErrorNegocio(Exception):
    pass


_ENTERO = re.compile(r"^\d{1,9}$")
_DECIMAL = re.compile(r"^\d{1,9}([.,]\d{1,2})?$")


def leer_entero(valor, campo="El valor"):
    """Dinero en pesos: solo dígitos. Rechaza letras, símbolos, negativos, 'NaN' y notación científica."""
    texto = str(valor if valor is not None else "").strip()
    if not _ENTERO.match(texto):
        raise ErrorNegocio(f"{campo}: escribe solo números enteros, sin letras, puntos ni símbolos.")
    return Decimal(texto)


def leer_decimal(valor, campo="El valor"):
    """Cantidades de insumos: dígitos y, opcionalmente, coma o punto con hasta 2 decimales."""
    texto = str(valor if valor is not None else "").strip()
    if not _DECIMAL.match(texto):
        raise ErrorNegocio(f"{campo}: escribe solo números (puedes usar coma para decimales), sin letras ni símbolos.")
    return Decimal(texto.replace(",", "."))


def auditar(usuario, accion, **detalle):
    RegistroAuditoria.objects.create(usuario=usuario, accion=accion, detalle=detalle)


def _leer_items(items):
    """Valida las líneas del pedido: ids y cantidades enteras positivas, con tope. Suma las líneas repetidas."""
    if not isinstance(items, (list, tuple)):
        raise ErrorNegocio("Datos del pedido no válidos.")
    pedidas = {}
    for i in items:
        try:
            pid, cant_txt = str(i["producto"]).strip(), str(i["cantidad"]).strip()
        except (KeyError, TypeError):
            raise ErrorNegocio("Datos del pedido no válidos.")
        if not _ENTERO.match(pid):
            raise ErrorNegocio("Hay un producto no válido en el pedido.")
        if not _ENTERO.match(cant_txt):
            raise ErrorNegocio("Las cantidades deben ser números enteros positivos (sin decimales ni signos).")
        cant = int(cant_txt)
        if cant == 0:
            continue                      # línea en cero: se ignora (el garzón la quitó)
        pedidas[int(pid)] = pedidas.get(int(pid), 0) + cant
    if any(c > MAX_CANTIDAD for c in pedidas.values()):
        raise ErrorNegocio(f"La cantidad máxima por producto es {MAX_CANTIDAD}.")
    return list(pedidas.items())


def _leer_agregados(agregados):
    """Valida los agregados del pedido (salsas, más papas, etc.): ids y cantidades enteras positivas, con tope.
    Es opcional: sin agregados devuelve una lista vacía."""
    if not agregados:
        return []
    if not isinstance(agregados, (list, tuple)):
        raise ErrorNegocio("Datos de los agregados no válidos.")
    pedidos = {}
    for a in agregados:
        try:
            aid, cant_txt = str(a["agregado"]).strip(), str(a["cantidad"]).strip()
        except (KeyError, TypeError):
            raise ErrorNegocio("Datos de los agregados no válidos.")
        if not _ENTERO.match(aid):
            raise ErrorNegocio("Hay un agregado no válido en el pedido.")
        if not _ENTERO.match(cant_txt):
            raise ErrorNegocio("Las cantidades de los agregados deben ser números enteros positivos.")
        cant = int(cant_txt)
        if cant == 0:
            continue
        pedidos[int(aid)] = pedidos.get(int(aid), 0) + cant
    if any(c > MAX_CANTIDAD for c in pedidos.values()):
        raise ErrorNegocio(f"La cantidad máxima por agregado es {MAX_CANTIDAD}.")
    return list(pedidos.items())


@transaction.atomic
def crear_pedido(usuario, canal, datos, items, observaciones="", agregados=None):
    """Pedido, comanda y descuento de stock se guardan JUNTOS en una sola transacción:
    si algo falla (por ejemplo, no hay stock) no queda nada guardado a medias."""
    if canal not in CANALES:
        raise ErrorNegocio("Debes elegir el canal de venta: Local, Retiro o Domicilio.")
    items = _leer_items(items)
    if not items:
        raise ErrorNegocio("El pedido no tiene productos.")
    productos = Producto.objects.in_bulk([p for p, _ in items])
    for pid, _ in items:
        prod = productos.get(pid)
        if not prod or not prod.activo:
            raise ErrorNegocio("Hay un producto que no existe o está inactivo.")
    agregados = _leer_agregados(agregados)
    extras = Agregado.objects.in_bulk([a for a, _ in agregados])
    for aid, _ in agregados:
        extra = extras.get(aid)
        if not extra or not extra.activo:
            raise ErrorNegocio("Hay un agregado que no existe o está inactivo.")
    base = {"usuario": usuario, "observaciones": (observaciones or "")[:200]}
    if canal == "local":
        mesa = str(datos.get("mesa", "")).strip()
        if not _ENTERO.match(mesa):
            raise ErrorNegocio("Indica el número de mesa.")
        pedido = PedidoLocal.objects.create(numero_mesa=int(mesa), **base)
    elif canal == "retiro":
        nombre = str(datos.get("nombre", "")).strip()
        if not nombre:
            raise ErrorNegocio("Indica el nombre de quien retira.")
        pedido = PedidoRetiro.objects.create(nombre_retiro=nombre[:100], **base)
    else:
        campos = {k: str(datos.get(k, "")).strip() for k in ("nombre", "telefono", "direccion")}
        faltan = [etq for k, etq in (("nombre", "el nombre"), ("telefono", "el teléfono"),
                                      ("direccion", "la dirección")) if not campos[k]]
        if faltan:
            raise ErrorNegocio("Para Domicilio falta indicar " + ", ".join(faltan[:-1]) +
                               (" y " if len(faltan) > 1 else "") + faltan[-1] + ".")
        envio = leer_entero(datos.get("envio") or "0", "Costo de envío")
        cliente = Cliente.objects.create(nombre=campos["nombre"][:100], telefono=campos["telefono"],
                                         direccion=campos["direccion"])
        pedido = PedidoDomicilio.objects.create(cliente=cliente, costo_envio=envio, **base)

    for pid, cant in items:
        prod = productos[pid]
        DetallePedido.objects.create(pedido=pedido, producto=prod, cantidad=cant, precio_unitario=prod.precio)
    for aid, cant in agregados:
        extra = extras[aid]
        DetalleAgregado.objects.create(pedido=pedido, agregado=extra, cantidad=cant, precio_unitario=extra.precio)
    pedido.total = pedido.calcular_total()
    pedido.save(update_fields=["total"])
    Comanda.objects.create(pedido=pedido)
    descontar_insumos(pedido.pk)          # misma transacción: si no hay stock, se deshace todo el pedido
    return pedido


def _fmt(x):
    return format(Decimal(x).normalize(), "f")


@transaction.atomic
def descontar_insumos(pedido_id):
    """RF03: descuenta insumos según receta; RF04: crea alerta si queda bajo el mínimo.
    Bloquea las filas de insumo (siempre en el mismo orden, para evitar bloqueos cruzados entre pedidos
    simultáneos) y NO permite vender más de lo que hay: el stock nunca queda negativo."""
    pedido = Pedido.objects.get(pk=pedido_id)
    necesarios = {}
    for det in pedido.detalles.select_related("producto"):
        for rec in Receta.objects.filter(producto=det.producto):
            necesarios[rec.insumo_id] = necesarios.get(rec.insumo_id, Decimal(0)) + rec.cantidad_por_unidad * det.cantidad
    for det in pedido.agregados.select_related("agregado"):          # los agregados descuentan igual que un producto
        for rec in RecetaAgregado.objects.filter(agregado=det.agregado):
            necesarios[rec.insumo_id] = necesarios.get(rec.insumo_id, Decimal(0)) + rec.cantidad_por_unidad * det.cantidad
    for insumo in Insumo.objects.select_for_update().filter(pk__in=necesarios).order_by("pk"):
        cant = necesarios[insumo.pk]
        if insumo.stock_actual < cant:
            raise ErrorNegocio(
                f"No hay stock suficiente de «{insumo.nombre}»: quedan {_fmt(insumo.stock_actual)} {insumo.unidad} "
                f"y el pedido necesita {_fmt(cant)}.")
        insumo.stock_actual -= cant
        insumo.save(update_fields=["stock_actual"])
        MovimientoInventario.objects.create(insumo=insumo, tipo="salida", cantidad=cant, pedido=pedido)
        if insumo.bajo_minimo() and not insumo.alertas.filter(atendida=False).exists():
            AlertaStock.objects.create(insumo=insumo)


@transaction.atomic
def cambiar_estado_comanda(comanda, nuevo):
    validos = {"pendiente": ("preparacion",), "preparacion": ("lista",)}
    if nuevo not in validos.get(comanda.estado, ()):
        raise ErrorNegocio("Cambio de estado no permitido.")
    comanda.estado = nuevo
    comanda.save(update_fields=["estado"])
    if nuevo == "lista":
        Pedido.objects.filter(pk=comanda.pedido_id).update(estado="listo")


@transaction.atomic
def anular_pedido(pedido, usuario, motivo):
    """El stock solo se repone si la cocina todavía no empezó a preparar el pedido.
    Si ya estaba en preparación o lista, los ingredientes se gastaron y el stock no cambia."""
    if pedido.estado == "anulado":
        raise ErrorNegocio("El pedido ya estaba anulado.")
    if not motivo.strip():
        raise ErrorNegocio("Indica el motivo de la anulación.")
    comanda = Comanda.objects.filter(pedido=pedido).first()
    repone = comanda is None or comanda.estado == "pendiente"
    if repone:
        for mov in MovimientoInventario.objects.filter(pedido=pedido, tipo="salida").select_related("insumo"):
            insumo = Insumo.objects.select_for_update().get(pk=mov.insumo_id)
            insumo.stock_actual += mov.cantidad
            insumo.save(update_fields=["stock_actual"])
            MovimientoInventario.objects.create(insumo=insumo, tipo="entrada", cantidad=mov.cantidad, pedido=pedido)
    pedido.estado = "anulado"
    pedido.save(update_fields=["estado"])
    auditar(usuario, "anulacion_pedido", pedido=pedido.pk, motivo=motivo, total=str(pedido.total),
            stock_repuesto="si" if repone else "no (ya estaba en preparación)")


@transaction.atomic
def registrar_entrada(insumo, cantidad, usuario):
    insumo.stock_actual += cantidad
    insumo.save(update_fields=["stock_actual"])
    MovimientoInventario.objects.create(insumo=insumo, tipo="entrada", cantidad=cantidad)
    if not insumo.bajo_minimo():
        insumo.alertas.filter(atendida=False).update(atendida=True)


@transaction.atomic
def ajustar_stock(insumo, nuevo, usuario, motivo):
    if not motivo.strip():
        raise ErrorNegocio("Indica el motivo del ajuste.")
    antes = insumo.stock_actual
    insumo.stock_actual = nuevo
    insumo.save(update_fields=["stock_actual"])
    MovimientoInventario.objects.create(insumo=insumo, tipo="ajuste", cantidad=nuevo - antes)
    auditar(usuario, "ajuste_stock", insumo=insumo.nombre, antes=str(antes), despues=str(nuevo), motivo=motivo)


@transaction.atomic
def registrar_pago(pedido, metodo, monto, usuario):
    if metodo not in Pago.Metodo.values:
        raise ErrorNegocio("Elige un medio de pago válido: efectivo, tarjeta o transferencia.")
    if pedido.estado == "anulado":
        raise ErrorNegocio("No se puede cobrar un pedido anulado.")
    if monto <= 0:
        raise ErrorNegocio("El monto debe ser mayor que cero.")
    if monto > pedido.saldo():
        raise ErrorNegocio("El monto supera el saldo pendiente del pedido.")
    Pago.objects.create(pedido=pedido, metodo=metodo, monto=monto, usuario=usuario)
    if pedido.saldo() == 0 and pedido.fecha_pago is None:   # estado «Pagado»
        pedido.fecha_pago = timezone.now()
        pedido.save(update_fields=["fecha_pago"])


def resumen_caja():
    """Pagos aún no incluidos en un cierre, sumados por método de pago."""
    filas = Pago.objects.filter(cierre__isnull=True).values("metodo").annotate(t=Sum("monto"))
    return {m: next((f["t"] for f in filas if f["metodo"] == m), Decimal(0)) for m, _ in Pago.Metodo.choices}


@transaction.atomic
def cerrar_caja(usuario, contados):
    """RF06: cuadra por método (efectivo, tarjeta, transferencia) contra lo registrado."""
    esperados = resumen_caja()
    desglose, esp_total, con_total = {}, Decimal(0), Decimal(0)
    for metodo, esperado in esperados.items():
        contado = leer_entero(contados.get(metodo) or "0", f"Contado en {metodo}")
        desglose[metodo] = {"esperado": str(esperado), "contado": str(contado), "diferencia": str(contado - esperado)}
        esp_total += esperado
        con_total += contado
    cierre = CierreCaja.objects.create(
        usuario=usuario, monto_esperado=esp_total, monto_contado=con_total,
        diferencia=con_total - esp_total, desglose=desglose)
    Pago.objects.filter(cierre__isnull=True).update(cierre=cierre)
    auditar(usuario, "cierre_caja_con_diferencia" if cierre.diferencia != 0 else "cierre_caja",
            cierre=cierre.pk, esperado=str(esp_total), contado=str(con_total), diferencia=str(cierre.diferencia))
    return cierre
