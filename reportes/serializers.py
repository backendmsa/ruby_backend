from rest_framework import serializers
from decimal import Decimal
from productos.nombres_articulos import nombre_visible

# ============================================================
# REPORTE DE VENTAS
# ============================================================

class ReporteVentaSerializer(
    serializers.Serializer
):

    id = serializers.UUIDField()

    folio = serializers.CharField()

    fecha = serializers.DateTimeField()

    usuario = serializers.SerializerMethodField()

    metodo_pago = serializers.CharField(
        source="metodo_pago.nombre"
    )

    subtotal = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    descuento = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    iva = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    total = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    estado = serializers.CharField()

    def get_usuario(self, obj):
        return f"{obj.usuario.nombre} {obj.usuario.apellido}"
    

# ============================================================
# PRODUCTOS MÁS VENDIDOS
# ============================================================

class ReporteProductoSerializer(
    serializers.Serializer
):

    producto = serializers.CharField()

    variante = serializers.CharField()

    cantidad_vendida = serializers.IntegerField()

    total_generado = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )


# ============================================================
# INVENTARIO
# ============================================================

class ReporteInventarioSerializer(
    serializers.Serializer
):

    id = serializers.UUIDField()

    producto = serializers.SerializerMethodField()
    variante = serializers.SerializerMethodField()

    def get_producto(self, obj):
        return nombre_visible(obj) if obj.nombre_completo else obj.producto.nombre

    def get_variante(self, obj):
        return "" if obj.nombre_completo else obj.nombre

    sku = serializers.CharField()

    codigo_barras = serializers.CharField()

    stock_actual = serializers.IntegerField(
        source="stock"
    )

    stock_defectuoso = serializers.IntegerField()

    stock_minimo = serializers.IntegerField()

    costo = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    precio_menudeo = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    precio_mayoreo = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    activo = serializers.BooleanField()

# ============================================================
# STOCK BAJO
# ============================================================

class ReporteStockBajoSerializer(
    serializers.Serializer
):

    id = serializers.UUIDField()

    producto = serializers.SerializerMethodField()
    variante = serializers.SerializerMethodField()

    def get_producto(self, obj):
        return nombre_visible(obj) if obj.nombre_completo else obj.producto.nombre

    def get_variante(self, obj):
        return "" if obj.nombre_completo else obj.nombre

    stock_actual = serializers.IntegerField(
        source="stock"
    )

    stock_defectuoso = serializers.IntegerField()

    stock_minimo = serializers.IntegerField()

    necesita_reposicion = serializers.SerializerMethodField()

    def get_necesita_reposicion(self, obj):
        return obj.stock <= obj.stock_minimo

# ============================================================
# CORTES DE CAJA
# ============================================================

class ReporteCorteSerializer(
    serializers.Serializer
):

    id = serializers.UUIDField()

    caja = serializers.CharField()

    usuario = serializers.CharField()

    fecha_inicio = serializers.DateTimeField()

    fecha_fin = serializers.DateTimeField(
        allow_null=True,
    )

    efectivo_inicial = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    total_ventas = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    numero_ventas = serializers.IntegerField()

    total_reembolsos = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    efectivo_esperado_actual = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    efectivo_final = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        allow_null=True,
    )

    diferencia = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        allow_null=True,
    )
    
# ============================================================
# DEVOLUCIONES
# ============================================================

class ReporteDevolucionProductoSerializer(
    serializers.Serializer
):

    producto = serializers.CharField()

    variante = serializers.CharField()

    cantidad = serializers.IntegerField()

    subtotal = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )


class ReporteDevolucionSerializer(
    serializers.Serializer
):

    id = serializers.UUIDField()

    venta_folio = serializers.CharField(
        source="venta.folio"
    )

    usuario = serializers.SerializerMethodField()

    tipo = serializers.CharField()
    motivo = serializers.CharField()
    estado = serializers.CharField()

    total_devuelto = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    productos = serializers.SerializerMethodField()

    fecha = serializers.DateTimeField()

    def get_usuario(self, obj):
        return f"{obj.usuario.nombre} {obj.usuario.apellido}"

    def get_productos(self, obj):

        productos = [
            {
                "producto": (
                    detalle.detalle_venta
                    .variante
                    .producto
                    .nombre
                ),
                "variante": (
                    detalle.detalle_venta
                    .variante
                    .nombre
                ),
                "cantidad": detalle.cantidad,
                "subtotal": (
                    detalle.subtotal
                    or Decimal("0.00")
                ),
            }
            for detalle in obj.detalles.all()
        ]

        return ReporteDevolucionProductoSerializer(
            productos,
            many=True,
        ).data
        



# ============================================================
# GARANTÍAS
# ============================================================

class ReporteGarantiaSerializer(
    serializers.Serializer
):

    id = serializers.UUIDField()

    venta_folio = serializers.CharField(
        source="venta.folio"
    )

    producto = serializers.CharField(
        source="variante.producto.nombre"
    )

    variante = serializers.CharField(
        source="variante.nombre"
    )

    variante_nueva = serializers.CharField(
        source="variante_nueva.nombre",
        allow_null=True,
    )

    cantidad = serializers.IntegerField()

    usuario = serializers.SerializerMethodField()

    motivo = serializers.CharField()

    estado = serializers.CharField()

    resolucion = serializers.CharField(
        allow_null=True,
    )

    observaciones = serializers.CharField(
        allow_null=True,
    )

    fecha = serializers.DateTimeField()

    fecha_actualizacion = serializers.DateTimeField()

    def get_usuario(self, obj):
        return f"{obj.usuario.nombre} {obj.usuario.apellido}"


# ============================================================
# MOVIMIENTOS DE INVENTARIO
# ============================================================

class ReporteMovimientoSerializer(
    serializers.Serializer
):

    id = serializers.UUIDField()

    producto = serializers.CharField(
        source="variante.producto.nombre"
    )

    variante = serializers.CharField(
        source="variante.nombre"
    )

    tipo = serializers.CharField()

    stock_anterior = serializers.IntegerField()

    cantidad = serializers.IntegerField()

    stock_nuevo = serializers.IntegerField()

    stock_defectuoso_anterior = serializers.IntegerField()

    stock_defectuoso_nuevo = serializers.IntegerField()

    observaciones = serializers.CharField(
        allow_null=True,
    )

    usuario = serializers.SerializerMethodField()

    fecha = serializers.DateTimeField()

    def get_usuario(self, obj):
        return f"{obj.usuario.nombre} {obj.usuario.apellido}"
    
    
# ============================================================
# RESUMEN DEL DÍA
# ============================================================

class ReporteResumenDiaSerializer(
    serializers.Serializer
):

    fecha = serializers.DateField()

    cantidad_ventas = serializers.IntegerField()

    subtotal = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    descuento = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    iva = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    total_vendido = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    reembolsos = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    venta_neta = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    metodos_pago = serializers.DictField(
        child=serializers.DecimalField(
            max_digits=12,
            decimal_places=2,
            coerce_to_string=True,
        )
    )

    reembolsos_por_metodo = serializers.DictField(
        child=serializers.DecimalField(
            max_digits=12,
            decimal_places=2,
            coerce_to_string=True,
        )
    )