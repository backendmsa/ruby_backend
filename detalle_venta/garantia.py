"""Cálculo de vigencia desde el plazo pactado al momento de la venta."""
from dateutil.relativedelta import relativedelta


def meses_de_garantia(detalle):
    """Usa la captura histórica si existe. NULL conserva regla de ventas antiguas.

    Nunca se rellenan las ventas anteriores con un plazo supuesto: su campo queda
    NULL y, para mantener compatibilidad, se consulta la variante actual.
    """
    if detalle.garantia_meses is not None:
        return detalle.garantia_meses
    return detalle.variante.garantia_meses


def fecha_vencimiento_de_garantia(detalle):
    meses = meses_de_garantia(detalle)
    if not meses:
        return None
    return detalle.venta.fecha + relativedelta(months=meses)
