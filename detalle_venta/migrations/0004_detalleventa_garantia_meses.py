from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("detalle_venta", "0003_detalleventa_detalle_venta_venta_variante_unica"),
    ]

    operations = [
        migrations.AddField(
            model_name="detalleventa",
            name="garantia_meses",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
    ]
