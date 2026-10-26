import uuid

from django.core.validators import MinValueValidator
from django.db import models

from ventas.models import Venta
from variantes.models import Variante


class DetalleVenta(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name="detalles",
    )

    variante = models.ForeignKey(
        Variante,
        on_delete=models.PROTECT,
        related_name="detalles_venta",
    )

    # Meses pactados al vender. NULL se reserva a ventas históricas sin captura.
    garantia_meses = models.PositiveIntegerField(null=True, blank=True)

    cantidad = models.PositiveIntegerField(
        validators=[
            MinValueValidator(1),
        ],
    )

    precio_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    descuento = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(0),
        ],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["venta", "variante"],
                name="detalle_venta_venta_variante_unica",
            ),
        ]

    def __str__(self):
        return f"{self.venta.folio} - {self.variante.nombre}"