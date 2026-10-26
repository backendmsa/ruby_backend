import uuid
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from cajas.models import Caja
from corte_caja.models import CorteCaja

from ventas.models import Venta
from detalle_venta.models import DetalleVenta
from variantes.models import Variante
from inventario.models import MovimientoInventario
from devoluciones.models import Devolucion, DetalleDevolucion
from bitacora.services import registrar_bitacora
from config.exceptions import BusinessException

from .models import Garantia
from detalle_venta.garantia import meses_de_garantia, fecha_vencimiento_de_garantia



# ============================================================
# HELPERS CREAR GARANTÍA
# ============================================================

def _validar_venta(venta_id, usuario):
    try:
        venta = Venta.objects.select_for_update().get(id=venta_id)
    except Venta.DoesNotExist:
        raise BusinessException("La venta no existe.")
    if venta.estado == "CANCELADA":
        raise BusinessException("No se puede crear una garantía para una venta cancelada.")
    if venta.estado == "DEVUELTA":
        raise BusinessException("No se puede crear una garantía para una venta devuelta.")
    if usuario.rol not in (0, 1) and venta.usuario_id != usuario.id:
        raise BusinessException(
            "No tienes permisos para crear una garantía sobre esta venta."
        )
    
    return venta

    


def _validar_detalle_variante(venta, data):
    try:
        detalle_venta = (
            DetalleVenta.objects
            .select_for_update()
            .get(id=data["detalle_venta_id"], venta=venta)
        )
    except DetalleVenta.DoesNotExist:
        raise BusinessException("El detalle de venta no existe o no pertenece a la venta indicada.")

    variante = detalle_venta.variante
    if str(variante.id) != str(data["variante_id"]):
        raise BusinessException("La variante no corresponde al detalle de venta.")
    return detalle_venta, variante


def _validar_vigencia(detalle_venta):
    if not meses_de_garantia(detalle_venta):
        raise BusinessException("Este producto no tiene garantía configurada.")
    fecha_limite = fecha_vencimiento_de_garantia(detalle_venta)
    if timezone.now() > fecha_limite:
        raise BusinessException(
            f"La garantía de este producto venció el {fecha_limite.strftime('%d/%m/%Y')}."
        )


def _validar_disponibilidad(detalle_venta, cantidad, garantia_id=None):
    
    garantias = Garantia.objects.filter(
        detalle_venta=detalle_venta,
        estado__in=["PENDIENTE", "APROBADA", "FINALIZADA"]
    )
    
    if garantia_id:
        garantias = garantias.exclude(id=garantia_id)
    
    cantidad_garantizada = (
        garantias
        .aggregate(total=Sum("cantidad"))["total"] or 0
    )
    cantidad_devuelta = (
        DetalleDevolucion.objects
        .filter(detalle_venta=detalle_venta, devolucion__estado__in=["PENDIENTE", "APROBADA"])
        .aggregate(total=Sum("cantidad"))["total"] or 0
    )
    disponible = max(detalle_venta.cantidad - cantidad_garantizada - cantidad_devuelta, 0)
    if cantidad > disponible:
        raise BusinessException(
            f"La cantidad solicitada supera las unidades disponibles para garantía. "
            f"Disponibles: {disponible}."
        )


# ============================================================
# HELPERS APROBAR GARANTÍA
# ============================================================

def _crear_movimiento(variante, tipo, stock_anterior, cantidad, stock_nuevo,
                      stock_defectuoso_anterior, stock_defectuoso_nuevo, observaciones, usuario):
    MovimientoInventario.objects.create(
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


def _aprobar_reemplazo(garantia, cantidad, usuario):
    variante = Variante.objects.select_for_update().get(id=garantia.variante_id)
    
    if not variante.activo:
        raise BusinessException(
            "No se puede realizar el reemplazo porque "
            "la variante original está inactiva." 
        )
    
    if not variante.producto.activo:
        raise BusinessException(
            "No se puede realizar el reemplazo porque "
            "el producto original está inactivo."
        )
    
    if variante.stock < cantidad:
        raise BusinessException(
            f"Stock insuficiente para realizar el reemplazo. "
            f"Stock disponible: {variante.stock}. Cantidad requerida: {cantidad}."
        )

    # Recibir defectuoso — no toca stock vendible
    stock_ant = variante.stock
    stock_def_ant = variante.stock_defectuoso
    stock_def_nuevo = stock_def_ant + cantidad
    variante.stock_defectuoso = stock_def_nuevo
    variante.save(update_fields=["stock", "stock_defectuoso", "fecha_actualizacion"])
    _crear_movimiento(variante, "GARANTIA", stock_ant, cantidad, stock_ant,
                      stock_def_ant, stock_def_nuevo,
                      f"Reemplazo por garantía {garantia.id} - entrada producto defectuoso", usuario)

    # Entregar nuevo — descuenta stock vendible
    stock_ant2 = variante.stock
    stock_nuevo2 = stock_ant2 - cantidad
    stock_def_actual = variante.stock_defectuoso
    variante.stock = stock_nuevo2
    variante.save(update_fields=["stock", "fecha_actualizacion"])
    _crear_movimiento(variante, "GARANTIA", stock_ant2, cantidad, stock_nuevo2,
                      stock_def_actual, stock_def_actual,
                      f"Reemplazo por garantía {garantia.id} - salida producto nuevo", usuario)


def _aprobar_cambio_producto(
    garantia,
    cantidad,
    data,
    usuario
):
    variante_nueva_id = data.get(
        "variante_nueva_id"
    )
    

    

    if not variante_nueva_id:
        raise BusinessException(
            "Debe especificar la variante nueva."
        )
        
    try:
        variante_nueva_id = uuid.UUID(
            str(variante_nueva_id)
        )
    except (ValueError, TypeError, AttributeError):
        raise BusinessException(
            "El identificador de la variante nueva "
            "no es un UUID válido."
        )

        # ======================================================
    # OBTENER Y BLOQUEAR AMBAS VARIANTES
    # EN ORDEN DETERMINÍSTICO
    # ======================================================

    variante_ids = sorted(
        [
            garantia.variante_id,
            variante_nueva_id,
        ],
        key=str
    )

    variantes = list(
        Variante.objects
        .select_for_update()
        .filter(
            id__in=variante_ids
        )
        .order_by("id")
    )

    variantes_map = {
        variante.id: variante
        for variante in variantes
    }

    if garantia.variante_id not in variantes_map:
        raise BusinessException(
            "La variante original no existe."
        )

    if variante_nueva_id not in variantes_map:
        raise BusinessException(
            "La variante nueva no existe."
        )

    variante_original = variantes_map[
        garantia.variante_id
    ]

    variante_nueva = variantes_map[
        variante_nueva_id
    ]
    
        # ======================================================
    # VALIDAR VARIANTE ORIGINAL
    # ======================================================

    if not variante_original.activo:
        raise BusinessException(
            "No se puede realizar el cambio porque "
            "la variante original está inactiva."
        )

    if not variante_original.producto.activo:
        raise BusinessException(
            "No se puede realizar el cambio porque "
            "el producto original está inactivo."
        )

    # ======================================================
    # VALIDAR VARIANTE NUEVA
    # ======================================================

    if not variante_nueva.activo:
        raise BusinessException(
            "No se puede realizar el cambio porque "
            "la variante nueva está inactiva."
        )

    if not variante_nueva.producto.activo:
        raise BusinessException(
            "No se puede realizar el cambio porque "
            "el producto de la variante nueva está inactivo."
        )

    if variante_original.id == variante_nueva.id:
        raise BusinessException(
            "La variante nueva debe ser diferente "
            "a la variante original."
        )

    if variante_nueva.stock < cantidad:
        raise BusinessException(
            f"Stock insuficiente en la variante nueva "
            f"para realizar el cambio. "
            f"Stock disponible: {variante_nueva.stock}. "
            f"Cantidad requerida: {cantidad}."
        )

    # ======================================================
    # ORIGINAL DEFECTUOSO REGRESA
    # ======================================================

    stock_orig_ant = variante_original.stock
    stock_orig_def_ant = variante_original.stock_defectuoso
    stock_orig_def_nuevo = (
        stock_orig_def_ant + cantidad
    )

    variante_original.stock_defectuoso = (
        stock_orig_def_nuevo
    )

    variante_original.save(
        update_fields=[
            "stock",
            "stock_defectuoso",
            "fecha_actualizacion"
        ]
    )

    _crear_movimiento(
        variante_original,
        "CAMBIO_PRODUCTO",
        stock_orig_ant,
        cantidad,
        stock_orig_ant,
        stock_orig_def_ant,
        stock_orig_def_nuevo,
        (
            f"Cambio de producto por garantía "
            f"{garantia.id} - entrada producto "
            f"original defectuoso"
        ),
        usuario
    )

    # ======================================================
    # NUEVA VARIANTE SALE
    # ======================================================

    stock_nueva_ant = variante_nueva.stock
    stock_nueva_nuevo = (
        stock_nueva_ant - cantidad
    )
    stock_nueva_def = (
        variante_nueva.stock_defectuoso
    )

    variante_nueva.stock = stock_nueva_nuevo

    variante_nueva.save(
        update_fields=[
            "stock",
            "fecha_actualizacion"
        ]
    )

    _crear_movimiento(
        variante_nueva,
        "CAMBIO_PRODUCTO",
        stock_nueva_ant,
        cantidad,
        stock_nueva_nuevo,
        stock_nueva_def,
        stock_nueva_def,
        (
            f"Cambio de producto por garantía "
            f"{garantia.id} - salida producto nuevo"
        ),
        usuario
    )

    garantia.variante_nueva = variante_nueva


def _aprobar_reparacion(garantia, cantidad, usuario):
    variante = Variante.objects.select_for_update().get(id=garantia.variante_id)

    if not variante.activo:
        raise BusinessException(
            "No se puede realizar la reparación porque la variante original está inactiva."
        )

    if not variante.producto.activo:
        raise BusinessException(
            "No se puede realizar la reparación porque el producto original está inactivo."
        )

    # Recibir producto defectuoso.
    # No entra al stock vendible.
    stock_ant = variante.stock
    stock_def_ant = variante.stock_defectuoso
    stock_def_nuevo = stock_def_ant + cantidad

    variante.stock_defectuoso = stock_def_nuevo
    variante.save(
        update_fields=[
            "stock",
            "stock_defectuoso",
            "fecha_actualizacion",
        ]
    )

    _crear_movimiento(
        variante,
        "GARANTIA",
        stock_ant,
        cantidad,
        stock_ant,
        stock_def_ant,
        stock_def_nuevo,
        f"Reparación por garantía {garantia.id} - entrada producto defectuoso",
        usuario,
    )
    
    
# ============================================================
# CREAR GARANTÍA
# ============================================================

@transaction.atomic
def crear_garantia(data, usuario):
    if not usuario.activo:
        raise BusinessException("El usuario no está activo.")
    
    venta = _validar_venta(data["venta_id"], usuario)
    detalle_venta, variante = _validar_detalle_variante(venta, data)

    cantidad = data["cantidad"]
    if cantidad <= 0:
        raise BusinessException("La cantidad debe ser mayor que cero.")
    if cantidad > detalle_venta.cantidad:
        raise BusinessException("La cantidad solicitada para garantía no puede superar la cantidad vendida.")

    _validar_vigencia(detalle_venta)
    _validar_disponibilidad(detalle_venta, cantidad)

    garantia = Garantia.objects.create(
        venta=venta,
        detalle_venta=detalle_venta,
        variante=variante,
        cantidad=cantidad,
        usuario=usuario,
        motivo=data["motivo"],
        estado="PENDIENTE",
    )

    registrar_bitacora(
        usuario=usuario,
        modulo="Garantias",
        accion="CREAR_GARANTIA",
        descripcion=(
            f"Garantía {garantia.id} registrada para la venta '{venta.folio}' por "
            f"{usuario.nombre} {usuario.apellido}. "
            f"Variante: '{variante.nombre}'. Cantidad: {cantidad}. Motivo: {garantia.motivo}."
        ),
    )
    return garantia


# ============================================================
# ACTUALIZAR GARANTÍA
# ============================================================

@transaction.atomic
def actualizar_garantia(garantia_id, data, usuario):

    if not usuario.activo:
        raise BusinessException(
            "El usuario no está activo."
        )

    try:
        garantia = (
            Garantia.objects
            .select_for_update()
            .get(id=garantia_id)
        )
    except Garantia.DoesNotExist:
        raise BusinessException(
            "La garantía no existe."
        )

    if garantia.estado != "PENDIENTE":
        raise BusinessException(
            "Solo se pueden modificar "
            "garantías pendientes."
        )

    if usuario.id != garantia.usuario_id:
        raise BusinessException(
            "No tienes permisos para "
            "modificar esta garantía."
        )

    motivo = data["motivo"]

    garantia.motivo = motivo

    garantia.save(
        update_fields=[
            "motivo",
            "fecha_actualizacion"
        ]
    )

    registrar_bitacora(
        usuario=usuario,
        modulo="Garantias",
        accion="MODIFICAR_GARANTIA",
        descripcion=(
            f"Garantía {garantia.id} modificada para la venta "
            f"'{garantia.venta.folio}' por "
            f"{usuario.nombre} {usuario.apellido}. "
            f"Motivo actualizado: {garantia.motivo}."
        ),
    )

    return garantia

# ============================================================
# APROBAR GARANTÍA
# ============================================================

@transaction.atomic
def aprobar_garantia(garantia_id, data, usuario):
    
    if not usuario.activo:
        raise BusinessException("El usuario no está activo.")
    
    # ========================================================
    # OBTENER GARANTÍA SIN BLOQUEAR
    # ========================================================

    try:
        garantia_base = (
            Garantia.objects
            .get(id=garantia_id)
        )
    except Garantia.DoesNotExist:
        raise BusinessException(
            "La garantía no existe."
        )
        
    # ========================================================
    # OBTENER VENTA SIN BLOQUEAR
    # ========================================================
    
    try:
        venta_base = (
            Venta.objects
            .select_related("corte_caja")
            .get(id=garantia_base.venta_id)
        )
    except Venta.DoesNotExist:
        raise BusinessException(
            "La venta asociada no existe."
        )
    if not venta_base.corte_caja:
        raise BusinessException("La venta no tiene un corte de caja asociado.")
    
    caja_id = venta_base.corte_caja.caja_id
    corte_caja_id = venta_base.corte_caja_id

    # ========================================================
    # LOCK 1: CAJA
    # ========================================================
    
    try:
        Caja.objects.select_for_update().get(
            id=caja_id
        )
    except Caja.DoesNotExist:
        raise BusinessException("La caja asociada a la venta no existe.")
    
    # ========================================================
    # LOCK 2: CORTE DE CAJA
    # ========================================================

    try:
        CorteCaja.objects.select_for_update().get(
            id=corte_caja_id,
            caja_id=caja_id,
        )
    except CorteCaja.DoesNotExist:
        raise BusinessException(
            "El corte de caja asociado a la venta no existe."
        )
    
    # ========================================================
    # LOCK 3: VENTA
    # ========================================================

    try:
        venta= (
            Venta.objects
            .select_for_update()
            .get(id=garantia_base.venta_id)
        )
    except Venta.DoesNotExist:
        raise BusinessException(
            "La venta asociada no existe."
        )

    if venta.estado == "CANCELADA":
        raise BusinessException(
            "No se puede aprobar una garantía "
            "de una venta cancelada."
        )

    if venta.estado == "DEVUELTA":
        raise BusinessException(
            "No se puede aprobar una garantía "
            "de una venta devuelta."
        )

    # ========================================================
    # LOCK 4: GARANTÍA
    # ========================================================

    try:
        garantia = (
            Garantia.objects
            .select_for_update()
            .get(id=garantia_id)
        )
    except Garantia.DoesNotExist:
        raise BusinessException(
            "La garantía no existe."
        )

    if garantia.estado != "PENDIENTE":
        raise BusinessException(
            "Solo se pueden aprobar garantías pendientes."
        )

    cantidad = garantia.cantidad
    resolucion = data["resolucion"]

    # ========================================================
    # LOCK 5: DETALLE DE VENTA
    # ========================================================

    try:
        detalle_venta = (
            DetalleVenta.objects
            .select_for_update()
            .get(
                id=garantia.detalle_venta_id,
                venta=venta
            )
        )
    except DetalleVenta.DoesNotExist:
        raise BusinessException(
            "El detalle de venta asociado no existe."
        )

    # ========================================================
    # VALIDAR QUE LA VARIANTE SIGA SIENDO LA CORRECTA
    # ========================================================

    if garantia.variante_id != detalle_venta.variante_id:
        raise BusinessException(
            "La variante de la garantía no corresponde "
            "al detalle de venta."
        )

    # ========================================================
    # VALIDAR DISPONIBILIDAD
    # ========================================================

    _validar_disponibilidad(
        detalle_venta,
        cantidad,
        garantia_id=garantia.id,
    )

    # ========================================================
    # RESOLUCIÓN
    # ========================================================

    if resolucion == "REEMPLAZO":

        _aprobar_reemplazo(
            garantia,
            cantidad,
            usuario
        )

    elif resolucion == "CAMBIO_PRODUCTO":

        _aprobar_cambio_producto(
            garantia,
            cantidad,
            data,
            usuario
        )

    elif resolucion == "REPARACION":
        _aprobar_reparacion(garantia, cantidad, usuario)

    # ========================================================
    # ACTUALIZAR GARANTÍA
    # ========================================================

    garantia.estado = "APROBADA"
    garantia.resolucion = resolucion
    garantia.observaciones = data.get(
        "observaciones"
    )

    garantia.save(
        update_fields=[
            "estado",
            "resolucion",
            "observaciones",
            "variante_nueva_id",
            "fecha_actualizacion",
        ]
    )

    # ========================================================
    # BITÁCORA
    # ========================================================

    registrar_bitacora(
        usuario=usuario,
        modulo="Garantias",
        accion="APROBAR_GARANTIA",
        descripcion=(
            f"Garantía {garantia.id} aprobada por "
            f"{usuario.nombre} {usuario.apellido}. "
            f"Venta: '{venta.folio}'. "
            f"Variante: '{garantia.variante.nombre}'. "
            f"Cantidad: {cantidad}. "
            f"Resolución: {resolucion}."
        ),
    )

    return garantia

# ============================================================
# RECHAZAR GARANTÍA
# ============================================================

@transaction.atomic
def rechazar_garantia(garantia_id, data, usuario):
    
    if not usuario.activo:
        raise BusinessException("El usuario no está activo.")


    try:
        garantia = Garantia.objects.select_for_update().get(id=garantia_id)
    except Garantia.DoesNotExist:
        raise BusinessException("La garantía no existe.")

    if garantia.estado != "PENDIENTE":
        raise BusinessException("Solo se pueden rechazar garantías pendientes.")

    garantia.estado = "RECHAZADA"
    garantia.observaciones = data.get("observaciones")
    garantia.save(update_fields=["estado", "observaciones", "fecha_actualizacion"])

    registrar_bitacora(
        usuario=usuario,
        modulo="Garantias",
        accion="RECHAZAR_GARANTIA",
        descripcion=(
            f"Garantía {garantia.id} rechazada por {usuario.nombre} {usuario.apellido}. "
            f"Venta: '{garantia.venta.folio}'. Variante: '{garantia.variante.nombre}'. "
            f"Cantidad: {garantia.cantidad}. "
            f"Observaciones: {garantia.observaciones or 'Sin observaciones'}."
        ),
    )
    return garantia


# ============================================================
# FINALIZAR GARANTÍA
# ============================================================

@transaction.atomic
def finalizar_garantia(garantia_id, data, usuario):
    if not usuario.activo:
        raise BusinessException("El usuario no está activo.")
    try:
        garantia = Garantia.objects.select_for_update().get(id=garantia_id)
    except Garantia.DoesNotExist:
        raise BusinessException("La garantía no existe.")

    if garantia.estado != "APROBADA":
        raise BusinessException("Solo se pueden finalizar garantías aprobadas.")

    garantia.estado = "FINALIZADA"
    if data.get("observaciones"):
        garantia.observaciones = data["observaciones"]
    garantia.save(update_fields=["estado", "observaciones", "fecha_actualizacion"])

    registrar_bitacora(
        usuario=usuario,
        modulo="Garantias",
        accion="FINALIZAR_GARANTIA",
        descripcion=(
            f"Garantía {garantia.id} finalizada por {usuario.nombre} {usuario.apellido}. "
            f"Venta: '{garantia.venta.folio}'. Variante: '{garantia.variante.nombre}'. "
            f"Cantidad: {garantia.cantidad}. "
            f"Resolución: {garantia.resolucion or 'No especificada'}."
        ),
    )
    return garantia
