"""Reglas de negocio. Las vistas solo validan permisos y llaman a estas funciones."""
import re
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import (
    AlertaStock, CierreCaja, Cliente, Comanda, DetallePedido, Insumo,
    MovimientoInventario, Pago, Pedido, PedidoDomicilio, PedidoLocal,
    PedidoRetiro, Producto, Receta, RegistroAuditoria,
)

CANALES = ("local", "retiro", "domicilio")


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


@transaction.atomic
def crear_pedido(usuario, canal, datos, items, observaciones=""):
    """Pedido y comanda se guardan juntos: si algo falla no queda un pedido sin comanda.
    El descuento de stock se hace después de confirmar (on_commit) y no hace esperar al garzón."""
    if canal not in CANALES:
        raise ErrorNegocio("Debes elegir el canal de venta: Local, Retiro o Domicilio.")
    items = [(int(i["producto"]), int(i["cantidad"])) for i in items if int(i["cantidad"]) > 0]
    if not items:
        raise ErrorNegocio("El pedido no tiene productos.")
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
        nombre, tel, dire = (str(datos.get(k, "")).strip() for k in ("nombre", "telefono", "direccion"))
        if not (nombre and tel and dire):
            raise ErrorNegocio("Para Domicilio indica nombre, teléfono y dirección.")
        envio = leer_entero(datos.get("envio") or "0", "Costo de envío")
        cliente = Cliente.objects.create(nombre=nombre[:100], telefono=tel, direccion=dire)
        pedido = PedidoDomicilio.objects.create(cliente=cliente, costo_envio=envio, **base)

    productos = Producto.objects.in_bulk([p for p, _ in items])
    for pid, cant in items:
        prod = productos.get(pid)
        if not prod or not prod.activo:
            raise ErrorNegocio("Hay un producto que no existe o está inactivo.")
        DetallePedido.objects.create(pedido=pedido, producto=prod, cantidad=cant, precio_unitario=prod.precio)
    pedido.total = pedido.calcular_total()
    pedido.save(update_fields=["total"])
    Comanda.objects.create(pedido=pedido)
    transaction.on_commit(lambda: descontar_insumos(pedido.pk))
    return pedido


@transaction.atomic
def descontar_insumos(pedido_id):
    """RF03: descuenta insumos según receta; RF04: crea alerta si queda bajo el mínimo."""
    pedido = Pedido.objects.get(pk=pedido_id)
    for det in pedido.detalles.select_related("producto"):
        for rec in Receta.objects.filter(producto=det.producto).select_related("insumo"):
            insumo = Insumo.objects.select_for_update().get(pk=rec.insumo_id)
            cant = rec.cantidad_por_unidad * det.cantidad
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
    if pedido.estado == "anulado":
        raise ErrorNegocio("El pedido ya estaba anulado.")
    if not motivo.strip():
        raise ErrorNegocio("Indica el motivo de la anulación.")
    for mov in MovimientoInventario.objects.filter(pedido=pedido, tipo="salida").select_related("insumo"):
        insumo = mov.insumo
        insumo.stock_actual += mov.cantidad
        insumo.save(update_fields=["stock_actual"])
        MovimientoInventario.objects.create(insumo=insumo, tipo="entrada", cantidad=mov.cantidad, pedido=pedido)
    pedido.estado = "anulado"
    pedido.save(update_fields=["estado"])
    auditar(usuario, "anulacion_pedido", pedido=pedido.pk, motivo=motivo, total=str(pedido.total))


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
    if pedido.estado == "anulado":
        raise ErrorNegocio("No se puede cobrar un pedido anulado.")
    if monto <= 0:
        raise ErrorNegocio("El monto debe ser mayor que cero.")
    if monto > pedido.saldo():
        raise ErrorNegocio("El monto supera el saldo pendiente del pedido.")
    Pago.objects.create(pedido=pedido, metodo=metodo, monto=monto, usuario=usuario)


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
    if cierre.diferencia != 0:
        auditar(usuario, "cierre_caja_con_diferencia", cierre=cierre.pk, diferencia=str(cierre.diferencia))
    return cierre
