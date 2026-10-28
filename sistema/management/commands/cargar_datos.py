"""Datos de ejemplo para probar el sistema: usuarios por rol, productos, insumos y recetas."""
from decimal import Decimal

from django.core.management.base import BaseCommand

from sistema.models import Insumo, Producto, Receta, Usuario

USUARIOS = [("garzon", "Garzón de prueba"), ("cocina", "Cocina de prueba"),
            ("cajero", "Cajero de prueba"), ("admin", "Administrador de prueba")]
INSUMOS = {"Pan de completo": ("un", 100, 20), "Vienesa": ("un", 100, 20), "Palta": ("kg", 8, 2),
           "Tomate": ("kg", 8, 2), "Mayonesa": ("kg", 5, 1), "Pan de hamburguesa": ("un", 60, 15),
           "Carne de hamburguesa": ("un", 60, 15), "Papas": ("kg", 25, 5), "Bebida 350 cc": ("un", 80, 20)}
PRODUCTOS = {"Completo italiano": (3200, {"Pan de completo": 1, "Vienesa": 1, "Palta": "0.05", "Tomate": "0.04", "Mayonesa": "0.02"}),
             "Completo as": (2800, {"Pan de completo": 1, "Vienesa": 1, "Mayonesa": "0.02"}),
             "Hamburguesa": (4500, {"Pan de hamburguesa": 1, "Carne de hamburguesa": 1, "Tomate": "0.03"}),
             "Papas fritas": (2500, {"Papas": "0.25"}), "Bebida": (1500, {"Bebida 350 cc": 1})}


class Command(BaseCommand):
    help = "Crea usuarios, productos, insumos y recetas de ejemplo (solo para desarrollo)."

    def handle(self, *args, **opts):
        for user, nombre in USUARIOS:
            u, nuevo = Usuario.objects.get_or_create(username=user, defaults={"first_name": nombre, "rol": user})
            if nuevo:
                u.set_password(user)  # clave de desarrollo = nombre de usuario; cámbiala antes de usar en el local
                u.is_staff = u.is_superuser = user == "admin"
                u.save()
        insumos = {}
        for nombre, (unidad, stock, minimo) in INSUMOS.items():
            insumos[nombre], _ = Insumo.objects.get_or_create(
                nombre=nombre, defaults={"unidad": unidad, "stock_actual": stock, "stock_minimo": minimo})
        for nombre, (precio, receta) in PRODUCTOS.items():
            prod, _ = Producto.objects.get_or_create(nombre=nombre, defaults={"precio": precio})
            for ins, cant in receta.items():
                Receta.objects.get_or_create(producto=prod, insumo=insumos[ins],
                                             defaults={"cantidad_por_unidad": Decimal(str(cant))})
        self.stdout.write(self.style.SUCCESS("Listo. Usuarios: garzon, cocina, cajero, admin (clave = nombre de usuario)."))
