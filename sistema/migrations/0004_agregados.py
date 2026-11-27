import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sistema", "0003_pagado_y_stock_no_negativo")]

    operations = [
        migrations.CreateModel(
            name="Agregado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=100)),
                ("precio", models.DecimalField(decimal_places=0, max_digits=10)),
                ("activo", models.BooleanField(default=True)),
            ],
            options={"ordering": ["nombre"]},
        ),
        migrations.CreateModel(
            name="RecetaAgregado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cantidad_por_unidad", models.DecimalField(decimal_places=3, max_digits=10)),
                ("agregado", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                               related_name="recetas", to="sistema.agregado")),
                ("insumo", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                             related_name="recetas_agregado", to="sistema.insumo")),
            ],
            options={"unique_together": {("agregado", "insumo")}},
        ),
        migrations.CreateModel(
            name="DetalleAgregado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cantidad", models.PositiveIntegerField()),
                ("precio_unitario", models.DecimalField(decimal_places=0, max_digits=10)),
                ("agregado", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="sistema.agregado")),
                ("pedido", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                             related_name="agregados", to="sistema.pedido")),
            ],
        ),
    ]
