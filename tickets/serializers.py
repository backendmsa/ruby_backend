from rest_framework import serializers


class EmpresaTicketSerializer(serializers.Serializer):

    nombre = serializers.CharField()
    telefono = serializers.CharField()
    direccion = serializers.CharField()
    rfc = serializers.CharField()
    mensaje_ticket = serializers.CharField()


class VentaTicketSerializer(serializers.Serializer):

    folio = serializers.CharField()
    fecha = serializers.DateTimeField()
    metodo_pago = serializers.CharField()
    # Campos opcionales: tickets de ventas anteriores continúan funcionando.
    efectivo_recibido = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True, required=False
    )
    cambio = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True, required=False
    )
    estado = serializers.CharField()


class UsuarioTicketSerializer(serializers.Serializer):

    nombre = serializers.CharField()


class ProductoTicketSerializer(serializers.Serializer):

    producto = serializers.CharField()
    variante = serializers.CharField()
    cantidad = serializers.IntegerField()

    precio = serializers.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    subtotal = serializers.DecimalField(
        max_digits=10,
        decimal_places=2
    )


class TotalesTicketSerializer(serializers.Serializer):

    subtotal = serializers.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    descuento = serializers.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    iva = serializers.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    total = serializers.DecimalField(
        max_digits=10,
        decimal_places=2
    )


class TicketSerializer(serializers.Serializer):

    empresa = EmpresaTicketSerializer()

    venta = VentaTicketSerializer()

    usuario = UsuarioTicketSerializer()

    productos = ProductoTicketSerializer(
        many=True
    )

    totales = TotalesTicketSerializer()