from decimal import Decimal

from rest_framework import serializers
from django.db.models import Sum

from ventas.models import Venta

from .models import CorteCaja, MovimientoCaja


class CorteCajaSerializer(
    serializers.ModelSerializer
):

    caja_nombre = serializers.CharField(
        source="caja.nombre",
        read_only=True
    )

    usuario_nombre = serializers.SerializerMethodField()

    total_ventas = serializers.SerializerMethodField()
    numero_ventas = serializers.SerializerMethodField()
    total_reembolsos = serializers.SerializerMethodField()
    efectivo_esperado_actual = serializers.SerializerMethodField()
    total_ventas_efectivo = serializers.SerializerMethodField()
    total_ventas_tarjeta = serializers.SerializerMethodField()
    total_ventas_transferencia = serializers.SerializerMethodField()
    total_reembolsos_efectivo = serializers.SerializerMethodField()
    total_reembolsos_tarjeta = serializers.SerializerMethodField()
    total_reembolsos_transferencia = serializers.SerializerMethodField()

    class Meta:

        model = CorteCaja

        fields = [
            "id",
            "caja",
            "caja_nombre",
            "usuario",
            "usuario_nombre",
            "fecha_inicio",
            "fecha_fin",
            "efectivo_inicial",
            "efectivo_final",
            "diferencia",
            "total_ventas",
            "numero_ventas",
            "total_reembolsos",
            "efectivo_esperado_actual",
            "total_ventas_efectivo",
            "total_ventas_tarjeta",
            "total_ventas_transferencia",
            "total_reembolsos_efectivo",
            "total_reembolsos_tarjeta",
            "total_reembolsos_transferencia",
        ]

        read_only_fields = [
            "id",
            "caja_nombre",
            "usuario",
            "usuario_nombre",
            "fecha_inicio",
            "fecha_fin",
            "diferencia",
        ]

    def get_usuario_nombre(self, obj):
        nombre = f"{obj.usuario.nombre} {obj.usuario.apellido}".strip()
        return nombre or obj.usuario.usuario

    def validate_efectivo_inicial(
        self,
        value
    ):

        if value < 0:

            raise serializers.ValidationError(
                "El efectivo inicial no puede ser negativo."
            )

        return value

    def validate_efectivo_final(
        self,
        value
    ):

        if value is not None and value < 0:

            raise serializers.ValidationError(
                "El efectivo final no puede ser negativo."
            )

        return value

    ESTADOS_VENTA_VALIDA = [
        "COMPLETADA",
        "DEVUELTA"
    ]

    def get_total_ventas(
        self,
        obj
    ):

        if hasattr(
            obj,
            "_total_ventas"
        ):

            return (
                obj._total_ventas
                or Decimal("0.00")
            )

        resultado = (
            Venta.objects
            .filter(
                corte_caja=obj,
                estado__in=self.ESTADOS_VENTA_VALIDA
            )
            .aggregate(
                total=Sum("total")
            )["total"]
        )

        return (
            resultado
            or Decimal("0.00")
        )

    def get_numero_ventas(
        self,
        obj
    ):

        if hasattr(
            obj,
            "_numero_ventas"
        ):

            return obj._numero_ventas

        return (
            Venta.objects
            .filter(
                corte_caja=obj,
                estado__in=self.ESTADOS_VENTA_VALIDA
            )
            .count()
        )

    def get_total_reembolsos(
        self,
        obj
    ):

        if hasattr(
            obj,
            "_total_reembolsos"
        ):

            return (
                obj._total_reembolsos
                or Decimal("0.00")
            )

        resultado = (
            MovimientoCaja.objects
            .filter(
                corte_caja=obj,
                tipo="REEMBOLSO"
            )
            .aggregate(
                total=Sum("monto")
            )["total"]
        )

        return (
            resultado
            or Decimal("0.00")
        )

    @staticmethod
    def _importe_por_metodo(obj, anotacion, modelo, metodo, *, es_reembolso=False):
        """Importe monetario por método; usa anotaciones en listas e historial."""
        if hasattr(obj, anotacion):
            return getattr(obj, anotacion) or Decimal("0.00")
        filtros = {"corte_caja": obj, "metodo_pago__nombre": metodo}
        if es_reembolso:
            filtros["tipo"] = "REEMBOLSO"
            return (modelo.objects.filter(**filtros).aggregate(total=Sum("monto"))["total"]
                    or Decimal("0.00"))
        filtros["estado__in"] = ["COMPLETADA", "DEVUELTA"]
        return (modelo.objects.filter(**filtros).aggregate(total=Sum("total"))["total"]
                or Decimal("0.00"))

    def get_total_ventas_efectivo(self, obj):
        return self._importe_por_metodo(obj, "_total_efectivo_ventas", Venta, "EFECTIVO")

    def get_total_ventas_tarjeta(self, obj):
        return self._importe_por_metodo(obj, "_total_tarjeta_ventas", Venta, "TARJETA")

    def get_total_ventas_transferencia(self, obj):
        return self._importe_por_metodo(obj, "_total_transferencia_ventas", Venta, "TRANSFERENCIA")

    def get_total_reembolsos_efectivo(self, obj):
        return self._importe_por_metodo(obj, "_total_reembolsos_efectivo", MovimientoCaja, "EFECTIVO", es_reembolso=True)

    def get_total_reembolsos_tarjeta(self, obj):
        return self._importe_por_metodo(obj, "_total_reembolsos_tarjeta", MovimientoCaja, "TARJETA", es_reembolso=True)

    def get_total_reembolsos_transferencia(self, obj):
        return self._importe_por_metodo(obj, "_total_reembolsos_transferencia", MovimientoCaja, "TRANSFERENCIA", es_reembolso=True)

    def get_efectivo_esperado_actual(
        self,
        obj
    ):

        if (
            hasattr(
                obj,
                "_total_efectivo_ventas"
            )
            and hasattr(
                obj,
                "_total_reembolsos_efectivo"
            )
        ):

            total_efectivo = (
                obj._total_efectivo_ventas
                or Decimal("0.00")
            )

            total_reembolsos_efectivo = (
                obj._total_reembolsos_efectivo
                or Decimal("0.00")
            )

            return (
                obj.efectivo_inicial
                + total_efectivo
                - total_reembolsos_efectivo
            )

        total_efectivo = (
            Venta.objects
            .filter(
                corte_caja=obj,
                estado__in=self.ESTADOS_VENTA_VALIDA,
                metodo_pago__nombre="EFECTIVO"
            )
            .aggregate(
                total=Sum("total")
            )["total"]
            or Decimal("0.00")
        )

        total_reembolsos_efectivo = (
            MovimientoCaja.objects
            .filter(
                corte_caja=obj,
                tipo="REEMBOLSO",
                metodo_pago__nombre="EFECTIVO"
            )
            .aggregate(
                total=Sum("monto")
            )["total"]
            or Decimal("0.00")
        )

        return (
            obj.efectivo_inicial
            + total_efectivo
            - total_reembolsos_efectivo
        )


class MovimientoCajaSerializer(
    serializers.ModelSerializer
):

    metodo_pago = serializers.CharField(
        source="metodo_pago.nombre",
        read_only=True
    )

    usuario = serializers.CharField(
        source="usuario.nombre",
        read_only=True
    )

    class Meta:

        model = MovimientoCaja

        fields = [
            "id",
            "corte_caja",
            "metodo_pago",
            "tipo",
            "monto",
            "devolucion",
            "observaciones",
            "usuario",
            "fecha",
        ]

        read_only_fields = [
            "id",
            "usuario",
            "fecha",
        ]