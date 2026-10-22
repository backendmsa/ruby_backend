import uuid
from typing import NamedTuple

from django.db import transaction

from variantes.models import Variante
from bitacora.services import registrar_bitacora
from config.exceptions import BusinessException

from .models import MovimientoInventario


class ResultadoMovimiento(NamedTuple):
    movimiento: object
    stock_anterior: int
    stock_nuevo: int
    stock_defectuoso_anterior: int
    stock_defectuoso_nuevo: int


class ResultadoAjuste(NamedTuple):
    movimiento: object
    stock_anterior: int
    stock_nuevo: int
    stock_defectuoso_anterior: int
    stock_defectuoso_nuevo: int
    tipo_ajuste: str


# ==============================================================
# CONSTANTES
# ==============================================================

MAX_CANTIDAD_MOVIMIENTO = 10_000


# ==============================================================
# VALIDACIONES COMUNES
# ==============================================================

def validar_uuid(valor):
    try:
        uuid.UUID(str(valor))
    except (TypeError, ValueError, AttributeError):
        raise BusinessException(
            "El identificador de la variante no es válido."
        )


def validar_observaciones(observaciones):
    """El motivo es opcional, pero si se proporciona debe ser texto."""
    if observaciones is None:
        return ""

    if not isinstance(observaciones, str):
        raise BusinessException(
            "Las observaciones deben ser texto."
        )

    return observaciones.strip()


def validar_cantidad(valor):
    if isinstance(valor, bool):
        raise BusinessException(
            "La cantidad debe ser un número entero."
        )

    if isinstance(valor, float) and not valor.is_integer():
        raise BusinessException(
            "La cantidad debe ser un número entero."
        )

    try:
        cantidad = int(valor)
    except (TypeError, ValueError):
        raise BusinessException(
            "La cantidad debe ser un número entero."
        )

    if cantidad <= 0:
        raise BusinessException(
            "La cantidad debe ser mayor a cero."
        )

    if cantidad > MAX_CANTIDAD_MOVIMIENTO:
        raise BusinessException(
            f"La cantidad no puede ser mayor a {MAX_CANTIDAD_MOVIMIENTO:,}."
        )

    return cantidad


def validar_stock_nuevo(valor):
    if isinstance(valor, bool):
        raise BusinessException(
            "El stock nuevo debe ser un número entero."
        )

    if isinstance(valor, float) and not valor.is_integer():
        raise BusinessException(
            "El stock nuevo debe ser un número entero."
        )

    try:
        stock_nuevo = int(valor)
    except (TypeError, ValueError):
        raise BusinessException(
            "El stock nuevo debe ser un número entero."
        )

    if stock_nuevo < 0:
        raise BusinessException(
            "El stock no puede ser negativo."
        )

    return stock_nuevo


def validar_variante_activa(variante):
    if not variante.activo:
        raise BusinessException(
            "La variante está inactiva."
        )


def validar_diferencia_ajuste(diferencia):
    cantidad = abs(diferencia)

    if cantidad > MAX_CANTIDAD_MOVIMIENTO:
        raise BusinessException(
            f"La cantidad ajustada no puede ser mayor a "
            f"{MAX_CANTIDAD_MOVIMIENTO:,}."
        )

    return cantidad


def obtener_variante_bloqueada(variante_id):
    try:
        return (
            Variante.objects
            .select_for_update()
            .get(id=variante_id)
        )
    except Variante.DoesNotExist:
        raise BusinessException(
            "La variante no existe."
        )


def validar_movimiento_manual(variante, observaciones):
    validar_variante_activa(variante)
    return validar_observaciones(observaciones)


# ==============================================================
# CREAR MOVIMIENTO
# ==============================================================

def _crear_movimiento(
    variante,
    tipo,
    stock_anterior,
    cantidad,
    stock_nuevo,
    stock_defectuoso_anterior,
    stock_defectuoso_nuevo,
    observaciones,
    usuario,
):
    return MovimientoInventario.objects.create(
        variante=variante,
        tipo=tipo,
        stock_anterior=stock_anterior,
        cantidad=cantidad,
        stock_nuevo=stock_nuevo,
        stock_defectuoso_anterior=stock_defectuoso_anterior,
        stock_defectuoso_nuevo=stock_defectuoso_nuevo,
        observaciones=observaciones,
        usuario=usuario,
    )


# ==============================================================
# ENTRADA
# ==============================================================

@transaction.atomic
def registrar_entrada(variante_id, cantidad, observaciones, usuario):
    validar_uuid(variante_id)
    cantidad = validar_cantidad(cantidad)

    variante = obtener_variante_bloqueada(variante_id)

    observaciones = validar_movimiento_manual(
        variante,
        observaciones,
    )

    stock_anterior = variante.stock
    stock_nuevo = stock_anterior + cantidad

    stock_defectuoso_anterior = variante.stock_defectuoso
    stock_defectuoso_nuevo = stock_defectuoso_anterior

    movimiento = _crear_movimiento(
        variante=variante,
        tipo="ENTRADA",
        stock_anterior=stock_anterior,
        cantidad=cantidad,
        stock_nuevo=stock_nuevo,
        stock_defectuoso_anterior=stock_defectuoso_anterior,
        stock_defectuoso_nuevo=stock_defectuoso_nuevo,
        observaciones=observaciones,
        usuario=usuario,
    )

    variante.stock = stock_nuevo

    variante.save(
        update_fields=[
            "stock",
            "fecha_actualizacion",
        ]
    )

    registrar_bitacora(
        usuario=usuario,
        modulo="Inventario",
        accion="ENTRADA_INVENTARIO",
        descripcion=(
            f"Entrada de inventario registrada para la variante "
            f"'{variante.nombre}' por "
            f"{usuario.nombre} {usuario.apellido}. "
            f"Stock anterior: {stock_anterior}. "
            f"Cantidad ingresada: {cantidad}. "
            f"Stock nuevo: {stock_nuevo}. "
            f"Observaciones: {observaciones}."
        ),
    )

    return ResultadoMovimiento(
        movimiento=movimiento,
        stock_anterior=stock_anterior,
        stock_nuevo=stock_nuevo,
        stock_defectuoso_anterior=stock_defectuoso_anterior,
        stock_defectuoso_nuevo=stock_defectuoso_nuevo,
    )


# ==============================================================
# SALIDA
# ==============================================================

@transaction.atomic
def registrar_salida(variante_id, cantidad, observaciones, usuario):
    validar_uuid(variante_id)
    cantidad = validar_cantidad(cantidad)

    variante = obtener_variante_bloqueada(variante_id)

    observaciones = validar_movimiento_manual(
        variante,
        observaciones,
    )

    stock_anterior = variante.stock

    if stock_anterior < cantidad:
        raise BusinessException(
            "Stock insuficiente.",
            data={
                "stock_actual": stock_anterior,
                "cantidad_solicitada": cantidad,
            },
        )

    stock_nuevo = stock_anterior - cantidad

    stock_defectuoso_anterior = variante.stock_defectuoso
    stock_defectuoso_nuevo = stock_defectuoso_anterior

    movimiento = _crear_movimiento(
        variante=variante,
        tipo="SALIDA",
        stock_anterior=stock_anterior,
        cantidad=cantidad,
        stock_nuevo=stock_nuevo,
        stock_defectuoso_anterior=stock_defectuoso_anterior,
        stock_defectuoso_nuevo=stock_defectuoso_nuevo,
        observaciones=observaciones,
        usuario=usuario,
    )

    variante.stock = stock_nuevo

    variante.save(
        update_fields=[
            "stock",
            "fecha_actualizacion",
        ]
    )

    registrar_bitacora(
        usuario=usuario,
        modulo="Inventario",
        accion="SALIDA_INVENTARIO",
        descripcion=(
            f"Salida de inventario registrada para la variante "
            f"'{variante.nombre}' por "
            f"{usuario.nombre} {usuario.apellido}. "
            f"Stock anterior: {stock_anterior}. "
            f"Cantidad retirada: {cantidad}. "
            f"Stock nuevo: {stock_nuevo}. "
            f"Observaciones: {observaciones}."
        ),
    )

    return ResultadoMovimiento(
        movimiento=movimiento,
        stock_anterior=stock_anterior,
        stock_nuevo=stock_nuevo,
        stock_defectuoso_anterior=stock_defectuoso_anterior,
        stock_defectuoso_nuevo=stock_defectuoso_nuevo,
    )


# ==============================================================
# AJUSTE
# ==============================================================

@transaction.atomic
def registrar_ajuste(
    variante_id,
    stock_nuevo_solicitado,
    observaciones,
    usuario,
):
    validar_uuid(variante_id)

    stock_nuevo_solicitado = validar_stock_nuevo(
        stock_nuevo_solicitado
    )

    variante = obtener_variante_bloqueada(variante_id)

    observaciones = validar_movimiento_manual(
        variante,
        observaciones,
    )

    stock_anterior = variante.stock

    diferencia = (
        stock_nuevo_solicitado - stock_anterior
    )

    if diferencia == 0:
        raise BusinessException(
            "El stock nuevo es igual al stock actual. "
            "No hay nada que ajustar."
        )

    cantidad = validar_diferencia_ajuste(diferencia)

    tipo_ajuste = (
        "AUMENTO"
        if diferencia > 0
        else "DISMINUCIÓN"
    )

    stock_defectuoso_anterior = variante.stock_defectuoso
    stock_defectuoso_nuevo = stock_defectuoso_anterior

    # Mantener la explicación automática del ajuste aunque no indiquen motivo.
    observacion_final = (
        f"{tipo_ajuste} de stock."
        + (f" {observaciones}" if observaciones else "")
    )

    movimiento = _crear_movimiento(
        variante=variante,
        tipo="AJUSTE",
        stock_anterior=stock_anterior,
        cantidad=cantidad,
        stock_nuevo=stock_nuevo_solicitado,
        stock_defectuoso_anterior=stock_defectuoso_anterior,
        stock_defectuoso_nuevo=stock_defectuoso_nuevo,
        observaciones=observacion_final,
        usuario=usuario,
    )

    variante.stock = stock_nuevo_solicitado

    variante.save(
        update_fields=[
            "stock",
            "fecha_actualizacion",
        ]
    )

    registrar_bitacora(
        usuario=usuario,
        modulo="Inventario",
        accion="AJUSTE_INVENTARIO",
        descripcion=(
            f"Ajuste de inventario realizado para la variante "
            f"'{variante.nombre}' por "
            f"{usuario.nombre} {usuario.apellido}. "
            f"Stock anterior: {stock_anterior}. "
            f"Cantidad ajustada: {cantidad}. "
            f"Stock nuevo: {stock_nuevo_solicitado}. "
            f"Tipo de ajuste: {tipo_ajuste}. "
            f"Observaciones: {observaciones}."
        ),
    )

    return ResultadoAjuste(
        movimiento=movimiento,
        stock_anterior=stock_anterior,
        stock_nuevo=stock_nuevo_solicitado,
        stock_defectuoso_anterior=stock_defectuoso_anterior,
        stock_defectuoso_nuevo=stock_defectuoso_nuevo,
        tipo_ajuste=tipo_ajuste,
    )
