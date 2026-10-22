from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0002_remove_venta_ventas_vent_folio_f7143d_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="venta",
            name="efectivo_recibido",
            field=models.DecimalField(
                max_digits=10,
                decimal_places=2,
                null=True,
                blank=True,
            ),
        ),
    ]
