from rest_framework import serializers

from .models import Variante


from decimal import Decimal

from categorias.models import Categoria
from variantes.precios import advertencias_precios
from rest_framework.fields import empty


class CategoriaOpcional(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        if isinstance(data, str) and not data.strip():
            return None
        return super().to_internal_value(data)


class DecimalOpcional(serializers.DecimalField):
    def run_validation(self, data=empty):
        if data is None or (isinstance(data, str) and not data.strip()):
            data = "0.00"
        return super().run_validation(data)


class VarianteSerializer(serializers.ModelSerializer):

    # ----------------------------------------------------------
    # Se permite recibir stock al CREAR una variante.
    # En actualización se bloquea desde validate().
    #
    # validators=[] evita que DRF agregue automáticamente el
    # UniqueValidator en inglés. La unicidad la controlamos aquí
    # con mensajes propios en español y el servicio/DB como
    # segunda barrera.
    # ----------------------------------------------------------

    producto_nombre = serializers.CharField(
        source="producto.nombre",
        read_only=True,
    )

    # Solo para PATCH/PUT. No cambia Variante.producto_id.
    categoria = CategoriaOpcional(
        queryset=Categoria.objects.all(), required=False,
        allow_null=True, write_only=True,
    )
    advertencias_precios = serializers.SerializerMethodField(read_only=True)

    costo = DecimalOpcional(
        max_digits=10, decimal_places=2, required=False,
        min_value=Decimal("0.00"),
    )
    precio_mayoreo = DecimalOpcional(
        max_digits=10, decimal_places=2, required=False,
        min_value=Decimal("0.00"),
    )
    
    sku = serializers.CharField(
        max_length=100,
        validators=[],
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    codigo_barras = serializers.CharField(
        max_length=100,
        validators=[],
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    stock = serializers.IntegerField(
        required=False,
        min_value=0,
        error_messages={
            "invalid": "El stock inicial debe ser un número entero.",
            "min_value": "El stock inicial no puede ser negativo.",
        },
    )
    
    stock_minimo = serializers.IntegerField(
        required=False,
        min_value=0,
        error_messages={
            "invalid": "El stock mínimo debe ser un número entero.",
            "min_value": "El stock mínimo no puede ser negativo.",
        },
    )

    garantia_meses = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        error_messages={
            "invalid": "La garantía debe ser un número entero.",
            "min_value": "La garantía no puede ser negativa.",
        },
    )

    class Meta:
        model = Variante
        fields = [
            "id",
            "producto",
            "producto_nombre",
            "categoria",
            "advertencias_precios",
            "codigo_barras",
            "sku",
            "nombre",
            "stock",
            "stock_defectuoso",
            "stock_minimo",
            "costo",
            "precio_menudeo",
            "precio_mayoreo",
            "garantia_meses",
            "activo",
            "fecha_creacion",
            "fecha_actualizacion",
        ]

        read_only_fields = [
            "id",
            "stock_defectuoso",
            "activo",
            "fecha_creacion",
            "fecha_actualizacion",
        ]

    # ==========================================================
    # NOMBRE
    # ==========================================================

    def get_fields(self):
        fields = super().get_fields()

    # ----------------------------------------------------------
    # En actualización, producto es inmutable y por lo tanto
    # no debe ser obligatorio enviarlo en PUT.
    #
    # En creación permanece obligatorio.
    # ----------------------------------------------------------
        if self.instance is not None:
            fields["producto"].required = False

        return fields
    
    def get_advertencias_precios(self, obj):
        return advertencias_precios(obj.costo, obj.precio_menudeo, obj.precio_mayoreo)

    def validate_nombre(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "El nombre de la variante no puede estar vacío."
            )

        return value

    # ==========================================================
    # SKU
    # ==========================================================

    def validate_sku(self, value):
        if value is None:
            return None

        value = value.strip().upper()

        if not value:
            return None

        if not all(
            caracter.isalnum() or caracter in "_-"
            for caracter in value
        ):
            raise serializers.ValidationError(
                "El SKU solo puede contener letras, números, "
                "guiones y guiones bajos."
            )

        queryset = Variante.objects.filter(sku__iexact=value)

        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "Ya existe una variante con este SKU."
            )

        return value

    # ==========================================================
    # CÓDIGO DE BARRAS
    # ==========================================================

    def validate_codigo_barras(self, value):
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        if not value.isdigit():
            raise serializers.ValidationError(
                "El código de barras solo puede contener números."
            )

        queryset = Variante.objects.filter(
            codigo_barras=value
        )

        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "Ya existe una variante con este código de barras."
            )

        return value

    # ==========================================================
    # COSTO
    # ==========================================================

    def validate_costo(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "El costo no puede ser negativo."
            )

        return value

    # ==========================================================
    # PRECIO MENUDEO
    # ==========================================================

    def validate_precio_menudeo(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "El precio de venta debe ser mayor que cero."
            )

        return value

    # ==========================================================
    # PRECIO MAYOREO
    # ==========================================================

    def validate_precio_mayoreo(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "El precio mayoreo no puede ser negativo."
            )

        return value

    # ==========================================================
    # VALIDACIONES GENERALES
    # ==========================================================

    def validate(self, data):

        # ------------------------------------------------------
        # ACTIVO
        # ------------------------------------------------------
        if "activo" in self.initial_data:
            raise serializers.ValidationError({
                "activo": (
                    "El estado activo no puede modificarse "
                    "directamente. Utiliza los endpoints "
                    "activar/desactivar."
                )
            })
        
        if self.instance is None and "categoria" in self.initial_data:
            raise serializers.ValidationError({
                "categoria": "Selecciona la categoría del producto al crearlo; aquí solo se edita."
            })

        if self.instance is not None and "producto" in self.initial_data:
            raise serializers.ValidationError({
                "producto": (
                    "El producto de una variante no puede modificarse."
                )
            })

        # ------------------------------------------------------
        # STOCK
        #
        # Crear:
        #   stock = stock inicial permitido.
        #
        # Actualizar:
        #   stock NO puede modificarse directamente.
        # ------------------------------------------------------
        if self.instance is not None and "stock" in data:
            raise serializers.ValidationError({
                "stock": (
                    "El stock no puede modificarse directamente. "
                    "Utiliza los movimientos de inventario."
                )
            })

        # ------------------------------------------------------
        # STOCK MÍNIMO
        # ------------------------------------------------------
        stock_minimo = data.get(
            "stock_minimo",
            self.instance.stock_minimo
            if self.instance is not None
            else 0,
        )

        if stock_minimo < 0:
            raise serializers.ValidationError({
                "stock_minimo": (
                    "El stock mínimo no puede ser negativo."
                )
            })

        # ------------------------------------------------------
        # GARANTÍA
        # ------------------------------------------------------
        garantia_meses = data.get(
            "garantia_meses",
            self.instance.garantia_meses
            if self.instance is not None
            else None,
        )

        if (
            garantia_meses is not None
            and garantia_meses < 0
        ):
            raise serializers.ValidationError({
                "garantia_meses": (
                    "La garantía debe ser un número entero "
                    "mayor o igual a 0."
                )
            })

        # ------------------------------------------------------
        # PRECIOS
        # ------------------------------------------------------
        costo = data.get(
            "costo",
            self.instance.costo
            if self.instance is not None
            else 0,
        )

        precio_menudeo = data.get(
            "precio_menudeo",
            self.instance.precio_menudeo
            if self.instance is not None
            else 0,
        )

        precio_mayoreo = data.get(
            "precio_mayoreo",
            self.instance.precio_mayoreo
            if self.instance is not None
            else 0,
        )

        # Precio de venta obligatorio para ALTA; en PATCH de artículos
        # históricos permitimos editar otros campos sin reescribir precios.
        if self.instance is None and precio_menudeo <= 0:
            raise serializers.ValidationError({
                "precio_menudeo": "El precio de venta debe ser mayor que cero."
            })
        # Venta o mayoreo bajo costo: solo advertencia en la respuesta.

        return data