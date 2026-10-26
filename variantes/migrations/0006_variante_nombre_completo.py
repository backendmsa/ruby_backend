from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('variantes', '0005_alter_variante_sku'),
    ]

    operations = [
        migrations.AddField(
            model_name='variante',
            name='nombre_completo',
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
    ]
