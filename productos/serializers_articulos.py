"""Entrada y salida del módulo sencillo: cada artículo es una Variante.

El nombre del Producto padre es un detalle interno del modelo histórico.
"""
from decimal import Decimal

from rest_framework import serializers
from rest_framework.fields import empty

from categorias.models import Categoria
from variantes.models import Variante
from variantes.precios import advertencias_precios
from productos.nombres_articulos import nombre_visible


class CategoriaOpcional(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        if isinstance(data, str) and not data.strip():
            return None
        return super().to_internal_value(data)


class DecimalOpcional(serializers.DecimalField):
    def run_validation(self, data=empty):
        # DRF rechaza null ANTES de to_internal_value; normalizar aquí.
        if data is None or (isinstance(data, str) and not data.strip()):
            data = "0.00"
        return super().run_validation(data)


class EnteroOpcional(serializers.IntegerField):
    def run_validation(self, data=empty):
        if data is None or (isinstance(data, str) and not data.strip()):
            data = 0
        return super().run_validation(data)


class RegistroArticuloSerializer(serializers.Serializer):
    # El único nombre proporcionado por el usuario es el de la VARIANTE.
    nombre = serializers.CharField(
        max_length=150, trim_whitespace=True,
        error_messages={
            "required": "El nombre del artículo es obligatorio.",
            "blank": "El nombre del artículo es obligatorio.",
        },
    )
    precio_menudeo = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"),
        error_messages={
            "required": "El precio de venta es obligatorio.",
            "null": "El precio de venta es obligatorio.",
            "min_value": "El precio de venta debe ser mayor que cero.",
        },
    )
    categoria = CategoriaOpcional(
        queryset=Categoria.objects.all(), required=False, allow_null=True,
    )
    sku = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True,
    )
    codigo_barras = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True,
    )
    costo = DecimalOpcional(
        max_digits=10, decimal_places=2, required=False,
        default=Decimal("0.00"), min_value=Decimal("0.00"),
    )
    precio_mayoreo = DecimalOpcional(
        max_digits=10, decimal_places=2, required=False,
        default=Decimal("0.00"), min_value=Decimal("0.00"),
    )
    # El campo stock representa SOLO el stock inicial durante esta alta.
    stock = EnteroOpcional(required=False, default=0, min_value=0, max_value=10000)
    stock_minimo = EnteroOpcional(required=False, default=0, min_value=0)

    def validate_nombre(self, value):
        if not value.strip():
            raise serializers.ValidationError("El nombre del artículo es obligatorio.")
        return value.strip()

    def validate_categoria(self, value):
        if value is not None and not value.activo:
            raise serializers.ValidationError("La categoría está inactiva.")
        return value

    def validate(self, attrs):
        # Bajo costo = advertencia informativa, no error.
        return attrs


class ArticuloGestionSerializer(serializers.ModelSerializer):
    # Solo lectura: no se guarda en Variante.nombre.
    nombre_mostrar = serializers.SerializerMethodField()
    advertencias_precios = serializers.SerializerMethodField()
    # La UI usa "nombre" de Variante SIN sumar Producto.nombre.
    variante_id = serializers.UUIDField(source="id", read_only=True)
    producto_id = serializers.UUIDField(
    read_only=True,
)
    categoria = serializers.UUIDField(source="producto.categoria_id", read_only=True)
    categoria_nombre = serializers.CharField(source="producto.categoria.nombre", read_only=True)

    class Meta:
        model = Variante
        fields = [
            "variante_id", "producto_id", "nombre", "nombre_mostrar", "advertencias_precios", "categoria", "categoria_nombre",
            "sku", "codigo_barras", "costo", "precio_menudeo", "precio_mayoreo",
            "stock", "stock_minimo", "activo", "fecha_actualizacion",
        ]
        read_only_fields = fields

    def get_advertencias_precios(self, obj):
        return advertencias_precios(obj.costo, obj.precio_menudeo, obj.precio_mayoreo)

    def get_nombre_mostrar(self, obj):
        return nombre_visible(obj)
