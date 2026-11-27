"""Datos de ejemplo para probar el sistema: usuarios por rol, productos, insumos y recetas."""
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sistema.models import Agregado, Insumo, Producto, Receta, RecetaAgregado, Usuario

USUARIOS = [("cocina", "Cocina de prueba"), ("admin", "Administrador de prueba")]
INSUMOS = {"Pan de completo": ("un", 100, 20), "Vienesa": ("un", 100, 20), "Palta": ("kg", 8, 2),
           "Tomate": ("kg", 8, 2), "Mayonesa": ("kg", 5, 1), "Pan de hamburguesa": ("un", 60, 15),
           "Carne de hamburguesa": ("un", 60, 15), "Papas": ("kg", 25, 5), "Bebida 350 cc": ("un", 80, 20),
           "Salsa de ají": ("kg", 3, 0.5), "Salsa de queso": ("kg", 3, 0.5)}
PRODUCTOS = {  # nombre: (precio, detalle, insumos por unidad vendida)
    "Completo italiano": (3200, "Pan de completo, vienesa, palta, tomate y mayonesa.",
                          {"Pan de completo": 1, "Vienesa": 1, "Palta": "0.05", "Tomate": "0.04", "Mayonesa": "0.02"}),
    "Completo as": (2800, "Pan de completo, vienesa y mayonesa.", {"Pan de completo": 1, "Vienesa": 1, "Mayonesa": "0.02"}),
    "Hamburguesa": (4500, "Pan de hamburguesa, carne y tomate.",
                    {"Pan de hamburguesa": 1, "Carne de hamburguesa": 1, "Tomate": "0.03"}),
    "Papas fritas": (2500, "Porción de papas fritas.", {"Papas": "0.25"}),
    "Bebida": (1500, "Bebida de 350 cc.", {"Bebida 350 cc": 1})}
AGREGADOS = {  # nombre: (precio, insumos por unidad vendida)
    "Salsa de ají": (500, {"Salsa de ají": "0.03"}),
    "Salsa de queso": (700, {"Salsa de queso": "0.04"}),
    "Más papas": (1200, {"Papas": "0.15"})}


class Command(BaseCommand):
    help = ("Crea usuarios, productos, insumos y recetas de ejemplo. Por seguridad, las claves de los usuarios son "
            "ALEATORIAS y se muestran una sola vez. Usa --demo solo en tu computador (clave = nombre de usuario).")

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true",
                            help="Solo para pruebas locales: clave igual al nombre de usuario (admin/admin).")

    def handle(self, *args, **opts):
        if opts["demo"]:
            host = (settings.DATABASES["default"].get("HOST") or "").lower()
            if host not in ("", "localhost", "127.0.0.1", "::1"):
                raise CommandError("--demo con claves débiles no se permite en una base de datos remota "
                                   f"({host}). Quita --demo para crear claves aleatorias.")
        claves = {}
        for user, nombre in USUARIOS:
            u, nuevo = Usuario.objects.get_or_create(username=user, defaults={"first_name": nombre, "rol": user})
            if nuevo:
                claves[user] = user if opts["demo"] else secrets.token_urlsafe(12)
                u.set_password(claves[user])
                u.is_staff = u.is_superuser = user == "admin"
                u.save()
        insumos = {}
        for nombre, (unidad, stock, minimo) in INSUMOS.items():
            insumos[nombre], _ = Insumo.objects.get_or_create(
                nombre=nombre, defaults={"unidad": unidad, "stock_actual": stock, "stock_minimo": minimo})
        for nombre, (precio, detalle, receta) in PRODUCTOS.items():
            prod, _ = Producto.objects.get_or_create(nombre=nombre, defaults={"precio": precio, "detalle": detalle})
            if not prod.detalle:
                Producto.objects.filter(pk=prod.pk).update(detalle=detalle)
            for ins, cant in receta.items():
                Receta.objects.get_or_create(producto=prod, insumo=insumos[ins],
                                             defaults={"cantidad_por_unidad": Decimal(str(cant))})
        for nombre, (precio, receta) in AGREGADOS.items():
            extra, _ = Agregado.objects.get_or_create(nombre=nombre, defaults={"precio": precio})
            for ins, cant in receta.items():
                RecetaAgregado.objects.get_or_create(agregado=extra, insumo=insumos[ins],
                                                     defaults={"cantidad_por_unidad": Decimal(str(cant))})
        self.stdout.write(self.style.SUCCESS("Listo: productos, agregados, insumos y recetas de ejemplo."))
        if claves:
            self.stdout.write("Usuarios creados (anota las claves, no se vuelven a mostrar):")
            for user, clave in claves.items():
                self.stdout.write(f"  {user}  /  {clave}")
            if not opts["demo"]:
                self.stdout.write("Cámbialas cuando quieras desde /admin/. Los usuarios que ya existían no se modificaron.")
        else:
            self.stdout.write("Los usuarios ya existían: no se modificaron sus claves.")
