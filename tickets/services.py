from empresa.models import Empresa

from config.exceptions import BusinessException
from productos.nombres_articulos import nombre_visible


def generar_ticket(venta):

    empresa = Empresa.objects.first()

    if not empresa:
        raise BusinessException(
            "No hay configuración de empresa."
        )

    return {
        "empresa": {
            "nombre": empresa.nombre,
            "telefono": empresa.telefono,
            "direccion": empresa.direccion,
            "rfc": empresa.rfc,
            "mensaje_ticket": empresa.mensaje_ticket,
        },

        "venta": {
            "folio": venta.folio,
            "fecha": venta.fecha,
            "metodo_pago": venta.metodo_pago.nombre,
            "efectivo_recibido": venta.efectivo_recibido,
            "cambio": (
                venta.efectivo_recibido - venta.total
                if venta.efectivo_recibido is not None else None
            ),
            "estado": venta.estado,
        },

        "usuario": {
            "nombre": venta.usuario.nombre,
        },

        "productos": [
            {
                "producto": (nombre_visible(d.variante) if d.variante.nombre_completo else d.variante.producto.nombre),
                "variante": ("" if d.variante.nombre_completo else d.variante.nombre),
                "cantidad": d.cantidad,
                "precio": d.precio_unitario,
                "subtotal": d.subtotal,
            }
            for d in venta.detalles.all()
        ],

        "totales": {
            "subtotal": venta.subtotal,
            "descuento": venta.descuento,
            "iva": venta.iva,
            "total": venta.total,
        },
    }