"""Respaldo y restauración de todos los datos de la aplicación (app «sistema»).

El archivo (.ccbk) va CIFRADO con la misma clave Fernet que protege teléfono y dirección de los clientes
(FIELD_ENCRYPTION_KEY). Sin esa clave no se puede leer. Contiene contraseñas en forma de hash y datos personales,
así que debe guardarse fuera del servidor y con acceso restringido."""
import io
import json
import os
import tempfile

from cryptography.fernet import InvalidToken
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from .campos import _fernet
from .models import (
    Agregado, DetalleAgregado, RecetaAgregado, AlertaStock, CierreCaja, Cliente, Comanda, DetallePedido, Insumo, MovimientoInventario,
    Pago, Pedido, Producto, Receta, RegistroAuditoria, Usuario,
)

MARCA = b"CCBK1:"
# Orden de borrado: primero lo que depende de otras tablas.
_BORRAR = (Pago, CierreCaja, MovimientoInventario, AlertaStock, Comanda, DetalleAgregado, DetallePedido, Pedido,
           Cliente, Receta, RecetaAgregado, Insumo, Agregado, Producto, RegistroAuditoria, Usuario)


class ErrorRespaldo(Exception):
    pass


def nombre_archivo():
    return f"respaldo-{timezone.localtime():%Y%m%d-%H%M}.ccbk"


def generar_respaldo() -> bytes:
    buf = io.StringIO()
    call_command("dumpdata", "sistema", use_natural_foreign_keys=True, stdout=buf)
    paquete = {"version": 1, "creado": timezone.now().isoformat(), "datos": json.loads(buf.getvalue())}
    return MARCA + _fernet().encrypt(json.dumps(paquete).encode())


def leer_respaldo(contenido: bytes) -> list:
    if not contenido.startswith(MARCA):
        raise ErrorRespaldo("El archivo no es un respaldo de El Combo Completo.")
    try:
        paquete = json.loads(_fernet().decrypt(contenido[len(MARCA):]))
    except InvalidToken:
        raise ErrorRespaldo("No se pudo abrir el respaldo: la clave (FIELD_ENCRYPTION_KEY) no coincide o el archivo está dañado.")
    if paquete.get("version") != 1:
        raise ErrorRespaldo("Versión de respaldo no compatible.")
    return paquete["datos"]


@transaction.atomic
def restaurar_respaldo(contenido: bytes):
    """Reemplaza TODOS los datos actuales por los del respaldo. Si algo falla, no se cambia nada."""
    datos = leer_respaldo(contenido)
    for modelo in _BORRAR:
        modelo.objects.all().delete()
    fd, ruta = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f)
        call_command("loaddata", ruta, verbosity=0)
    finally:
        os.remove(ruta)
