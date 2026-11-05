"""Vuelve a cifrar teléfono y dirección de los clientes con la clave actual (tras cambiar o rotar la clave)."""
from django.core.management.base import BaseCommand
from django.db import connection

from sistema.campos import DATO_NO_LEGIBLE, _fernet
from sistema.models import Cliente


class Command(BaseCommand):
    help = ("Re-cifra los datos de clientes con la clave actual. Si SECRET_KEY cambió, define antes la variable "
            "DJANGO_SECRET_KEY_ANTERIORES con la clave antigua para poder leerlos.")

    def handle(self, *args, **opts):
        f, ok, perdidos = _fernet(), 0, 0
        for c in Cliente.objects.all():                       # al leer, ya se descifra con cualquiera de las claves
            if DATO_NO_LEGIBLE in (c.telefono, c.direccion):
                perdidos += 1
                continue
            with connection.cursor() as cur:                  # se guarda por SQL parametrizado para re-cifrar en un paso
                cur.execute("UPDATE sistema_cliente SET telefono=%s, direccion=%s WHERE id=%s",
                            [f.encrypt(c.telefono.encode()).decode(), f.encrypt(c.direccion.encode()).decode(), c.pk])
            ok += 1
        self.stdout.write(self.style.SUCCESS(f"Re-cifrados: {ok}."))
        if perdidos:
            self.stdout.write(self.style.WARNING(
                f"{perdidos} cliente(s) siguen ilegibles: se cifraron con una clave que no está disponible. "
                "Si eran datos de prueba, bórralos desde el panel /admin/."))
