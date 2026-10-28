from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models

from .campos import TextoCifrado


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        GARZON = "garzon", "Garzón"
        COCINA = "cocina", "Personal de cocina"
        CAJERO = "cajero", "Cajero"
        ADMIN = "admin", "Administrador"

    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.GARZON)

    def tiene_rol(self, *roles):
        return self.is_superuser or self.rol == "admin" or self.rol in roles




class Cliente(models.Model):
    """Solo existe para pedidos a Domicilio. Teléfono y dirección van cifrados."""
    nombre = models.CharField(max_length=100)
    telefono = TextoCifrado()
    direccion = TextoCifrado()

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    precio = models.DecimalField(max_digits=10, decimal_places=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Insumo(models.Model):
    """El stock se controla por Insumo (ingrediente), no por Producto."""
    nombre = models.CharField(max_length=100)
    unidad = models.CharField(max_length=20, default="un")
    stock_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def bajo_minimo(self):
        return self.stock_actual <= self.stock_minimo


class Receta(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="recetas")
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, related_name="recetas")
    cantidad_por_unidad = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        unique_together = ("producto", "insumo")


class Pedido(models.Model):
    """Clase base. El canal se resuelve por herencia (Local, Retiro, Domicilio)."""
    class Estado(models.TextChoices):
        ACTIVO = "activo", "En curso"
        LISTO = "listo", "Listo para entregar"
        ENTREGADO = "entregado", "Entregado"
        ANULADO = "anulado", "Anulado"

    fecha_hora = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)
    total = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    observaciones = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="pedidos")

    class Meta:
        ordering = ["-fecha_hora"]

    @property
    def canal(self):
        if hasattr(self, "pedidolocal"):
            return "Local"
        if hasattr(self, "pedidoretiro"):
            return "Retiro"
        if hasattr(self, "pedidodomicilio"):
            return "Domicilio"
        return "—"

    @property
    def referencia(self):
        if hasattr(self, "pedidolocal"):
            return f"Mesa {self.pedidolocal.numero_mesa}"
        if hasattr(self, "pedidoretiro"):
            return self.pedidoretiro.nombre_retiro
        if hasattr(self, "pedidodomicilio"):
            return self.pedidodomicilio.cliente.nombre
        return ""

    def calcular_total(self):
        suma = sum((d.subtotal() for d in self.detalles.all()), Decimal(0))
        if hasattr(self, "pedidodomicilio"):
            suma += self.pedidodomicilio.costo_envio
        return suma

    def pagado(self):
        return sum((p.monto for p in self.pagos.all()), Decimal(0))

    def saldo(self):
        return self.total - self.pagado()

    def __str__(self):
        return f"Pedido #{self.pk}"


class PedidoLocal(Pedido):
    numero_mesa = models.PositiveIntegerField()


class PedidoRetiro(Pedido):
    nombre_retiro = models.CharField(max_length=100)


class PedidoDomicilio(Pedido):
    costo_envio = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="pedidos")


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="detalles")  # composición
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=0)

    def subtotal(self):
        return self.precio_unitario * self.cantidad


class Comanda(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_PREPARACION = "preparacion", "En preparación"
        LISTA = "lista", "Lista"

    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE, related_name="comanda")
    hora_llegada = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)

    class Meta:
        ordering = ["hora_llegada"]


class MovimientoInventario(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SALIDA = "salida", "Salida por venta"
        AJUSTE = "ajuste", "Ajuste manual"

    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    pedido = models.ForeignKey(Pedido, null=True, blank=True, on_delete=models.SET_NULL)


class AlertaStock(models.Model):
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name="alertas")
    fecha_hora = models.DateTimeField(auto_now_add=True)
    atendida = models.BooleanField(default=False)

    class Meta:
        ordering = ["-fecha_hora"]


class CierreCaja(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    monto_esperado = models.DecimalField(max_digits=12, decimal_places=0)
    monto_contado = models.DecimalField(max_digits=12, decimal_places=0)
    diferencia = models.DecimalField(max_digits=12, decimal_places=0)
    desglose = models.JSONField(default=dict)

    class Meta:
        ordering = ["-fecha_hora"]


class Pago(models.Model):
    class Metodo(models.TextChoices):
        EFECTIVO = "efectivo", "Efectivo"
        TARJETA = "tarjeta", "Tarjeta"
        TRANSFERENCIA = "transferencia", "Transferencia"

    pedido = models.ForeignKey(Pedido, on_delete=models.PROTECT, related_name="pagos")
    monto = models.DecimalField(max_digits=12, decimal_places=0)
    metodo = models.CharField(max_length=14, choices=Metodo.choices)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT)
    cierre = models.ForeignKey(CierreCaja, null=True, blank=True, on_delete=models.SET_NULL, related_name="pagos")


class RegistroAuditoria(models.Model):
    """En el diseño va en MongoDB; aquí se guarda en un JSONField de la misma base."""
    fecha_hora = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(Usuario, null=True, on_delete=models.SET_NULL)
    accion = models.CharField(max_length=60)
    detalle = models.JSONField(default=dict)

    class Meta:
        ordering = ["-fecha_hora"]
