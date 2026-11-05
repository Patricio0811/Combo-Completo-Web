"""Campo de texto cifrado (Fernet) para teléfono y dirección de clientes.

Claves (la primera cifra; todas sirven para descifrar, así se puede rotar la clave sin perder datos):
  1. FIELD_ENCRYPTION_KEY  (en settings o variable de entorno): una o varias claves Fernet separadas por comas.
  2. Si no existe, se deriva de SECRET_KEY.
  3. DJANGO_SECRET_KEY_ANTERIORES: SECRET_KEY antiguas (separadas por comas), solo para poder LEER datos
     guardados cuando la SECRET_KEY era otra. Después se re-cifran con `python manage.py reencriptar_clientes`.
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models

log = logging.getLogger(__name__)
DATO_NO_LEGIBLE = "[dato cifrado con otra clave: no se puede leer]"


def _derivar(texto):
    return base64.urlsafe_b64encode(hashlib.sha256(texto.encode()).digest())


def _lista(valor):
    return [v.strip() for v in str(valor or "").split(",") if v.strip()]


def _fernet():
    claves = _lista(getattr(settings, "FIELD_ENCRYPTION_KEY", None) or os.environ.get("FIELD_ENCRYPTION_KEY"))
    claves = [c.encode() for c in claves] or [_derivar(settings.SECRET_KEY)]
    claves += [_derivar(s) for s in _lista(os.environ.get("DJANGO_SECRET_KEY_ANTERIORES"))]
    return MultiFernet([Fernet(c) for c in claves])


class TextoCifrado(models.TextField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        if value == DATO_NO_LEGIBLE:    # evita sobrescribir con el aviso un dato que aún podría recuperarse
            raise ValueError("No se puede guardar un dato que no pudo descifrarse.")
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Antes esto tumbaba la pantalla completa (error 500). Ahora se avisa y el sistema sigue funcionando.
            log.warning("Un dato cifrado no se pudo leer: fue guardado con otra clave (¿cambió SECRET_KEY?).")
            return DATO_NO_LEGIBLE
