from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("sistema", "0004_agregados")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name="pedido", name="fecha_pago"),
                migrations.RemoveConstraint(model_name="insumo", name="insumo_stock_no_negativo"),
                migrations.RemoveConstraint(model_name="insumo", name="insumo_minimo_no_negativo"),
            ],
        ),
    ]
