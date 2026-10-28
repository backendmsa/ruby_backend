"""Edición explícita de precios de venta de variantes, sin alterar modelos ni stock."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from bitacora.services import registrar_bitacora
from config.exceptions import BusinessException
from variantes.models import Variante


MAX_VARIANTES = 200


class CambioPrecioMasivoSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_VARIANTES,
        allow_empty=False,
    )
    precio_menudeo = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    confirmado = serializers.BooleanField(required=True)

    def validate_ids(self, ids):
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Hay variantes repetidas en la selección.")
        return ids

    def validate_confirmado(self, confirmado):
        if confirmado is not True:
            raise serializers.ValidationError("Confirma el cambio masivo antes de guardar.")
        return confirmado


@transaction.atomic
def actualizar_precios_masivos(*, ids, precio, usuario):
    """Todo o nada: limita la operación a IDs explícitos y precio de venta."""
    if not usuario.is_authenticated or not usuario.activo or usuario.rol not in (0, 1, 2):
        raise BusinessException("No tienes permisos para actualizar precios masivos.")

    # Bloqueo determinista para evitar esperas circulares entre ediciones simultáneas.
    ordenados = sorted(ids, key=str)
    variantes = list(
        Variante.objects.select_for_update()
        .filter(pk__in=ordenados)
        .order_by("id")
    )
    if len(variantes) != len(ordenados):
        raise BusinessException(
            "La selección cambió o contiene variantes inexistentes. Actualiza la pantalla."
        )

    modificadas = sum(variante.precio_menudeo != precio for variante in variantes)
    ahora = timezone.now()
    Variante.objects.filter(pk__in=ordenados).update(
        precio_menudeo=precio,
        fecha_actualizacion=ahora,
    )

    registrar_bitacora(
        usuario=usuario,
        modulo="Variantes",
        accion="PRECIO_MASIVO",
        descripcion=(
            f"Precio de venta masivo a ${precio:.2f} MXN; "
            f"{len(variantes)} variantes seleccionadas, {modificadas} con cambio. "
            f"IDs: {', '.join(str(i) for i in ordenados)}"
        ),
    )
    return {"actualizadas": len(variantes), "modificadas": modificadas}
