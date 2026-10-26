from rest_framework import serializers

from .models import Garantia
from detalle_venta.garantia import meses_de_garantia, fecha_vencimiento_de_garantia


class CrearGarantiaSerializer(serializers.Serializer):

    venta_id = serializers.UUIDField()

    detalle_venta_id = serializers.UUIDField()

    variante_id = serializers.UUIDField()

    cantidad = serializers.IntegerField(
        min_value=1
    )

    motivo = serializers.CharField(
        allow_blank=False
    )
    
class ActualizarGarantiaSerializer(serializers.Serializer):

    motivo = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            "required": "El campo 'motivo' es obligatorio.",
            "blank": "El motivo no puede estar vacío.",
        }
    )

    def to_internal_value(self, data):

        campos_permitidos = {"motivo"}
        campos_enviados = set(data.keys())

        campos_no_permitidos = (
            campos_enviados - campos_permitidos
        )

        if campos_no_permitidos:

            campo = next(
                iter(campos_no_permitidos)
            )

            raise serializers.ValidationError({
                "non_field_errors": [
                    f"El campo '{campo}' no puede modificarse."
                ]
            })

        return super().to_internal_value(data)


class AprobarGarantiaSerializer(serializers.Serializer):

    resolucion = serializers.ChoiceField(
        choices=[
            "REEMPLAZO",
            "CAMBIO_PRODUCTO",
            "REPARACION"
        ]
    )

    variante_nueva_id = serializers.UUIDField(
        required=False,
        allow_null=True
    )

    observaciones = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )

    def validate(self, data):

        resolucion = data.get("resolucion")
        variante_nueva_id = data.get(
            "variante_nueva_id"
        )

        if (
            resolucion == "CAMBIO_PRODUCTO"
            and not variante_nueva_id
        ):
            raise serializers.ValidationError(
                "variante_nueva_id es obligatorio "
                "para CAMBIO_PRODUCTO."
            )

        if (
            resolucion != "CAMBIO_PRODUCTO"
            and variante_nueva_id
        ):
            raise serializers.ValidationError(
                "variante_nueva_id solo debe enviarse "
                "cuando la resolución sea CAMBIO_PRODUCTO."
            )

        return data


class RechazarGarantiaSerializer(serializers.Serializer):

    observaciones = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )


class FinalizarGarantiaSerializer(serializers.Serializer):

    observaciones = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )


class GarantiaSerializer(serializers.ModelSerializer):

    venta = serializers.CharField(
        source="venta.folio"
    )

    usuario = serializers.CharField(
        source="usuario.nombre"
    )

    variante = serializers.CharField(
        source="variante.nombre"
    )

    producto = serializers.CharField(
        source="variante.producto.nombre"
    )

    variante_nueva = serializers.CharField(
        source="variante_nueva.nombre",
        allow_null=True
    )

    garantia_meses = serializers.SerializerMethodField()
    fecha_vencimiento = serializers.SerializerMethodField()
    garantia_plazo_historico = serializers.SerializerMethodField()

    def get_garantia_meses(self, obj):
        return meses_de_garantia(obj.detalle_venta)

    def get_fecha_vencimiento(self, obj):
        return fecha_vencimiento_de_garantia(obj.detalle_venta)

    def get_garantia_plazo_historico(self, obj):
        return obj.detalle_venta.garantia_meses is not None

    class Meta:

        model = Garantia

        fields = [
            "id",
            "venta",
            "usuario",
            "producto",
            "variante",
            "variante_nueva",
            "cantidad",
            "garantia_meses",
            "fecha_vencimiento",
            "garantia_plazo_historico",
            "motivo",
            "estado",
            "resolucion",
            "observaciones",
            "fecha",
            "fecha_actualizacion",
        ]