from django.db import migrations, models
from django.db.models import F, Sum


def preparar_datos(apps, schema_editor):
    """Normaliza el stock con un movimiento de ajuste y marca los pedidos ya saldados."""
    db_alias = schema_editor.connection.alias
    Insumo = apps.get_model("sistema", "Insumo")
    MovimientoInventario = apps.get_model("sistema", "MovimientoInventario")
    negativos = Insumo.objects.using(db_alias).filter(stock_actual__lt=0).values_list("pk", "stock_actual")
    for insumo_id, stock in negativos.iterator():
        MovimientoInventario.objects.using(db_alias).create(
            insumo_id=insumo_id, tipo="ajuste", cantidad=-stock)
        Insumo.objects.using(db_alias).filter(pk=insumo_id).update(stock_actual=0)
    Insumo.objects.using(db_alias).filter(stock_minimo__lt=0).update(stock_minimo=0)
    Pedido = apps.get_model("sistema", "Pedido")
    Pago = apps.get_model("sistema", "Pago")
    saldados = (Pago.objects.using(db_alias).values("pedido_id").annotate(t=Sum("monto"), ult=models.Max("fecha_hora"))
                .filter(t__gte=F("pedido__total"), pedido__total__gt=0).exclude(pedido__estado="anulado"))
    for fila in saldados:
        Pedido.objects.using(db_alias).filter(
            pk=fila["pedido_id"], fecha_pago__isnull=True).update(fecha_pago=fila["ult"])


class Migration(migrations.Migration):
    dependencies = [("sistema", "0002_producto_detalle")]

    operations = [
        migrations.AddField(
            model_name="pedido", name="fecha_pago",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Pagado el")),
        migrations.RunPython(preparar_datos, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="insumo",
            constraint=models.CheckConstraint(condition=models.Q(("stock_actual__gte", 0)), name="insumo_stock_no_negativo")),
        migrations.AddConstraint(
            model_name="insumo",
            constraint=models.CheckConstraint(condition=models.Q(("stock_minimo__gte", 0)), name="insumo_minimo_no_negativo")),
    ]
