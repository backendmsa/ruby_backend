import uuid

from django.db import models

from usuarios.models import Usuario
from corte_caja.models import CorteCaja
from metodos_pago.models import MetodoPago


class Venta(models.Model):

    ESTADOS = [
        ("COMPLETADA", "COMPLETADA"),
        ("CANCELADA", "CANCELADA"),
        ("DEVUELTA", "DEVUELTA"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    folio = models.CharField(
        max_length=30,
        unique=True,
    )

    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="ventas",
    )

    corte_caja = models.ForeignKey(
        CorteCaja,
        on_delete=models.PROTECT,
        related_name="ventas",
    )

    metodo_pago = models.ForeignKey(
        MetodoPago,
        on_delete=models.PROTECT,
        related_name="ventas",
    )

    fecha = models.DateTimeField(
        auto_now_add=True,
    )

    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    descuento = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        )

    iva = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    # Opcional para mantener compatibilidad con ventas antiguas y otros clientes.
    # Es la cantidad entregada por el cliente, NO el ingreso de la caja.
    efectivo_recibido = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="COMPLETADA",
    )

    class Meta:

        ordering = [
            "-fecha",
        ]

        indexes = [
            models.Index(
                fields=["fecha"],
                name="venta_fecha_idx",
            ),
            models.Index(
                fields=["corte_caja", "estado"],
                name="venta_corte_estado_idx",
            ),
        ]

    def __str__(self):
        return self.folio