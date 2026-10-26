import uuid

from django.db import models
from django.db.models.functions import Lower

from productos.models import Producto

class Variante(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name="variantes"
    )

    codigo_barras = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    sku = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    nombre = models.CharField(
        max_length=150
    )

    # Nombre de gestión opcional para renombrar de forma independiente una
    # presentación histórica cuyo Producto padre es compartido.
    nombre_completo = models.CharField(
        max_length=150, null=True, blank=True,
    )

    # ==========================================================
    # STOCK VENDIBLE
    # ==========================================================

    stock = models.PositiveIntegerField(
        default=0
    )

    # ==========================================================
    # STOCK DE PRODUCTOS DEFECTUOSOS
    # ==========================================================

    stock_defectuoso = models.PositiveIntegerField(
        default=0
    )

    stock_minimo = models.PositiveIntegerField(
        default=0
    )

    costo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    precio_menudeo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )

    precio_mayoreo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )

    garantia_meses = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    activo = models.BooleanField(
        default=True
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True
    )

    fecha_actualizacion = models.DateTimeField(
        auto_now=True
    )
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("sku"),
                name="variante_sku_lower_unico",
            ),
        ]

        indexes = [
            models.Index(
                fields=["producto", "activo"],
                name="variante_producto_activo_idx",
            ),
        ]

    def __str__(self):

        return (
            f"{self.producto.nombre} - "
            f"{self.nombre}"
        )