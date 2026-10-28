"""Campo de texto cifrado (Fernet) para teléfono y dirección de clientes."""
import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models


def _fernet():
    clave = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not clave:
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        clave = base64.urlsafe_b64encode(digest)
    return Fernet(clave)


class TextoCifrado(models.TextField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        return _fernet().decrypt(value.encode()).decode()
