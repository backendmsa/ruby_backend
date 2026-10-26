from decimal import Decimal, ROUND_HALF_UP 
from dateutil.relativedelta import relativedelta

from django.db import models, transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone 
from datetime import timedelta

from ventas.models import Venta 
from empresa.models import Empresa 
from detalle_venta.models import DetalleVenta 
from detalle_venta.garantia import meses_de_garantia, fecha_vencimiento_de_garantia
from inventario.models import MovimientoInventario 
from cajas.models import Caja 
from corte_caja.models import MovimientoCaja, CorteCaja 
from garantias.models import Garantia 
from variantes.models import Variante 
from bitacora.services import registrar_bitacora 
from config.exceptions import BusinessException 
 
from .models import Devolucion, DetalleDevolucion 
 
from metodos_pago.models import MetodoPago 
 
_Q = Decimal("0.01") 
 
 
def _redondear(valor): 
    return valor.quantize( 
        _Q, 
        rounding=ROUND_HALF_UP 
    ) 
 
 
# ============================================================ 
# HELPERS CREAR DEVOLUCIÓN 
# ============================================================ 
 
def _validar_venta_devolucion(venta_id, usuario): 
 
 
 
     
    try: 
 
        venta = ( 
            Venta.objects 
            .select_for_update() 
            .get(id=venta_id) 
        ) 
 
    except Venta.DoesNotExist: 
 
        raise BusinessException( 
            "La venta no existe." 
        ) 
 
    if venta.estado == "CANCELADA": 
 
        raise BusinessException( 
            "No se puede devolver una venta cancelada." 
        ) 
 
    if venta.estado == "DEVUELTA": 
 
        raise BusinessException( 
            "La venta ya fue devuelta completamente." 
        ) 
         
    if usuario.rol not in (0, 1) and venta.usuario_id != usuario.id: 
        raise BusinessException( 
            "No tienes permisos para devolver esta venta." 
        ) 
 
    return venta 
 
 
def _validar_plazo(venta, tipo): 
 
    if tipo != "NORMAL": 
        return 
 
    empresa = Empresa.objects.first() 
 
    if not empresa: 
 
        raise BusinessException( 
            "No existe configuración de empresa." 
        ) 
        
    fecha_limite = (
        venta.fecha + timedelta(days=empresa.dias_devolucion)
    )
 
    if timezone.now() > fecha_limite:
        raise BusinessException( 
            "El periodo de devolución expiró." 
        ) 
def _validar_garantia(devolucion):
    venta = devolucion.venta

    detalles = list(
        devolucion.detalles.select_related(
            "detalle_venta__variante"
        )
    )

    if not detalles:
        raise BusinessException(
            "La devolución no contiene productos."
        )

    ahora = timezone.now()

    for detalle in detalles:
        detalle_venta = detalle.detalle_venta

        if not meses_de_garantia(detalle_venta):
            raise BusinessException(
                "Este producto no tiene garantía configurada."
            )

        fecha_limite = fecha_vencimiento_de_garantia(detalle_venta)

        if ahora > fecha_limite:
            raise BusinessException(
                "La garantía de este producto venció el "
                f"{fecha_limite.strftime('%d/%m/%Y')}."
            )           


def _calcular_factor_reembolso(venta): 
 
    subtotal_bruto = ( 
        DetalleVenta.objects 
        .filter(venta=venta) 
        .aggregate( 
            total=models.Sum("subtotal") 
        )["total"] 
        or Decimal("0.00") 
    ) 
 
    subtotal_bruto = _redondear( 
        subtotal_bruto 
    ) 
 
    if subtotal_bruto <= 0: 
 
        raise BusinessException( 
            "La venta no tiene un subtotal válido." 
        ) 
 
    return venta.subtotal / subtotal_bruto 
 
 
def _disponible_para_devolucion( 
    detalle_venta 
): 
 
    cantidad_devuelta = ( 
        DetalleDevolucion.objects 
        .filter( 
            detalle_venta=detalle_venta, 
            devolucion__estado__in=[ 
                "PENDIENTE", 
                "APROBADA" 
            ] 
        ) 
        .aggregate( 
            total=models.Sum("cantidad") 
        )["total"] 
        or 0 
    ) 
 
    cantidad_garantizada = ( 
        Garantia.objects 
        .filter( 
            detalle_venta=detalle_venta, 
            estado__in=[ 
                "PENDIENTE", 
                "APROBADA", 
                "FINALIZADA", 
            ] 
        ) 
         
        .aggregate( 
            total=models.Sum("cantidad") 
        )["total"] 
        or 0 
    ) 
 
    return max( 
        detalle_venta.cantidad 
        - cantidad_devuelta 
        - cantidad_garantizada, 
        0 
    ) 
 
 
def _crear_detalles_devolucion( 
    devolucion, 
    venta, 
    productos, 
    factor_reembolso 
): 
 
    total = Decimal("0.00") 
    
    
    detalle_venta_ids = [
        item["detalle_venta_id"]
        for item in productos
    ]
    
    if len(detalle_venta_ids) != len(set(detalle_venta_ids)):
        raise BusinessException(
            "No se puede repetir un producto dentro de la misma devolución."
        )
 
    for item in productos: 
 
        try: 
 
            detalle_venta = ( 
                DetalleVenta.objects 
                .select_for_update() 
                .get( 
                    id=item["detalle_venta_id"], 
                    venta=venta 
                ) 
            ) 
 
        except DetalleVenta.DoesNotExist: 
 
            raise BusinessException( 
                "El producto no pertenece a la venta." 
            ) 
 
        cantidad = item["cantidad"] 
 
        if cantidad <= 0: 
 
            raise BusinessException( 
                "La cantidad debe ser mayor a cero." 
            ) 
 
        disponible = ( 
            _disponible_para_devolucion( 
                detalle_venta 
            ) 
        ) 
 
        if cantidad > disponible: 
 
            raise BusinessException( 
                "La cantidad solicitada para devolución " 
                "supera las unidades disponibles. " 
                f"Disponibles: {disponible}." 
            ) 
 
        subtotal_bruto = _redondear( 
            cantidad * detalle_venta.precio_unitario 
        ) 
 
        subtotal = _redondear( 
            subtotal_bruto * factor_reembolso 
        ) 
 
        DetalleDevolucion.objects.create( 
            devolucion=devolucion, 
            detalle_venta=detalle_venta, 
            cantidad=cantidad, 
            precio_original=detalle_venta.precio_unitario, 
            subtotal=subtotal, 
        ) 
 
        total += subtotal 
 
    return _redondear(total) 
 
 
def _calcular_total_devuelto( 
    venta, 
    total 
): 
 
    if total <= 0: 
 
        raise BusinessException( 
            "El importe de la devolución debe ser mayor que cero." 
        ) 
 
    if venta.subtotal > 0: 
 
        iva_devolucion = _redondear( 
            (total * venta.iva) / venta.subtotal 
        ) 
 
    else: 
 
        iva_devolucion = Decimal("0.00") 
 
    total_devuelto = _redondear( 
        total + iva_devolucion 
    ) 
 
    return min( 
        total_devuelto, 
        venta.total 
    ) 
 
 
# ============================================================ 
# HELPERS APROBAR DEVOLUCIÓN 
# ============================================================ 
 
def _validar_cantidades_aprobacion(detalles, devolucion): 
    detalle_ids = [ 
        detalle.detalle_venta_id 
        for detalle in detalles 
    ] 
 
    if not detalle_ids: 
        return 
 
    cantidades_devoluciones = ( 
        DetalleDevolucion.objects 
        .filter( 
            detalle_venta_id__in=detalle_ids, 
            devolucion__estado__in=["APROBADA", "PENDIENTE"], 
        ) 
        .exclude( 
            devolucion_id=devolucion.id 
        ) 
        .values("detalle_venta_id") 
        .annotate( 
            cantidad_aprobada=models.Sum( 
                "cantidad", 
                filter=models.Q( 
                    devolucion__estado="APROBADA" 
                ), 
            ), 
            cantidad_pendiente=models.Sum( 
                "cantidad", 
                filter=models.Q( 
                    devolucion__estado="PENDIENTE" 
                ), 
            ), 
        ) 
    ) 
 
    cantidades_devoluciones_map = { 
        item["detalle_venta_id"]: { 
            "aprobada": item["cantidad_aprobada"] or 0, 
            "pendiente": item["cantidad_pendiente"] or 0, 
        } 
        for item in cantidades_devoluciones 
    } 
 
    cantidades_garantias = ( 
        Garantia.objects 
        .filter( 
            detalle_venta_id__in=detalle_ids, 
            estado__in=["PENDIENTE", "APROBADA", "FINALIZADA"], 
        ) 
        .values("detalle_venta_id") 
        .annotate( 
            total=models.Sum("cantidad") 
        ) 
    ) 
 
    cantidades_garantias_map = { 
        item["detalle_venta_id"]: item["total"] or 0 
        for item in cantidades_garantias 
    } 
 
    for detalle in detalles: 
        detalle_venta = detalle.detalle_venta 
        detalle_id = detalle.detalle_venta_id 
 
        cantidades = cantidades_devoluciones_map.get( 
            detalle_id, 
            { 
                "aprobada": 0, 
                "pendiente": 0, 
            }, 
        ) 
 
        cantidad_aprobada = cantidades["aprobada"] 
        cantidad_pendiente = cantidades["pendiente"] 
 
        cantidad_garantizada = cantidades_garantias_map.get( 
            detalle_id, 
            0, 
        ) 
 
        disponible = max( 
            detalle_venta.cantidad 
            - cantidad_aprobada 
            - cantidad_pendiente 
            - cantidad_garantizada, 
            0, 
        ) 
 
        if detalle.cantidad > disponible: 
            raise BusinessException( 
                "La cantidad devuelta supera " 
                "la cantidad disponible." 
            ) 
def _reponer_stock(
    detalles,
    devolucion,
    usuario
):

    variante_ids = sorted(
        {
            detalle.detalle_venta.variante_id
            for detalle in detalles
        },
        key=str,
    )

    variantes = (
        Variante.objects
        .select_for_update()
        .filter(id__in=variante_ids)
        .order_by("id")
    )

    variantes_map = {
        variante.id: variante
        for variante in variantes
    }

    if len(variantes_map) != len(variante_ids):
        raise BusinessException(
            "Una o más variantes de la devolución no existen."
        )

    for detalle in sorted(
        detalles,
        key=lambda d: str(d.detalle_venta.variante_id),
    ):
        variante = variantes_map[
            detalle.detalle_venta.variante_id
        ]

        stock_ant = variante.stock
        stock_def_ant = variante.stock_defectuoso

        if devolucion.tipo == "DEFECTUOSO":

            stock_nuevo = stock_ant

            stock_def_nuevo = (
                stock_def_ant
                + detalle.cantidad
            )

        else:

            stock_nuevo = (
                stock_ant
                + detalle.cantidad
            )

            stock_def_nuevo = stock_def_ant

        MovimientoInventario.objects.create(
            variante=variante,
            tipo="DEVOLUCION",
            stock_anterior=stock_ant,
            cantidad=detalle.cantidad,
            stock_nuevo=stock_nuevo,
            stock_defectuoso_anterior=stock_def_ant,
            stock_defectuoso_nuevo=stock_def_nuevo,
            observaciones=(
                f"Devolución {devolucion.id}"
            ),
            usuario=usuario,
        )

        variante.stock = stock_nuevo
        variante.stock_defectuoso = stock_def_nuevo

        variante.save(
            update_fields=[
                "stock",
                "stock_defectuoso",
                "fecha_actualizacion",
            ]
        )
         
 
 
        
def _venta_completamente_devuelta(venta):
    cantidades_devueltas = (
        DetalleDevolucion.objects
        .filter(
            detalle_venta_id=OuterRef("pk"),
            devolucion__estado="APROBADA",
        )
        .values("detalle_venta_id")
        .annotate(
            total=models.Sum("cantidad")
        )
        .values("total")[:1]
    )

    detalles = (
        DetalleVenta.objects
        .filter(venta=venta)
        .annotate(
            cantidad_devuelta=Subquery(
                cantidades_devueltas
            )
        )
        .values(
            "cantidad",
            "cantidad_devuelta",
        )
    )

    for detalle in detalles:
        devuelto = detalle["cantidad_devuelta"] or 0

        if devuelto < detalle["cantidad"]:
            return False

    return True
 
 
# ============================================================ 
# CREAR DEVOLUCIÓN 
# ============================================================ 
 
@transaction.atomic 
def crear_devolucion( 
    data, 
    usuario 
): 
 
    venta = _validar_venta_devolucion( 
        data["venta_id"], 
        usuario 
    ) 
 
    _validar_plazo( 
        venta, 
        data["tipo"] 
    )
    
    if data["tipo"] == "EXTRAORDINARIA":
        if usuario.rol not in (0, 1):
            raise BusinessException(
                "Solo un administrador puede autorizar "
                "devoluciones extraordinarias."
            )
 
    # ======================================================== 
    # MÉTODO DE REEMBOLSO AUTOMÁTICO 
    # ======================================================== 
 
# ========================================================
# MÉTODO DE REEMBOLSO
# ========================================================

    try:
        metodo_pago_reembolso = (
            MetodoPago.objects
            .get(
                id=data["metodo_pago_reembolso_id"],
                activo=True
            )
        )

    except MetodoPago.DoesNotExist:
        raise BusinessException(
            "El método de reembolso "
            "no existe o está inactivo."
        )
 
    factor_reembolso = ( 
        _calcular_factor_reembolso( 
            venta 
        ) 
    ) 
 
    devolucion = Devolucion.objects.create( 
        venta=venta, 
        usuario=usuario, 
        metodo_pago_reembolso=metodo_pago_reembolso, 
        tipo=data["tipo"], 
        motivo=data["motivo"], 
        estado="PENDIENTE", 
    ) 
 
    total = _crear_detalles_devolucion( 
        devolucion, 
        venta, 
        data["productos"], 
        factor_reembolso 
    )
    if devolucion.tipo == "GARANTIA":
        _validar_garantia(devolucion)
 
    devolucion.total_devuelto = ( 
        _calcular_total_devuelto( 
            venta, 
            total 
        ) 
    ) 
 
    devolucion.save( 
        update_fields=[ 
            "total_devuelto" 
        ] 
    ) 
 
    registrar_bitacora( 
        usuario=usuario, 
        modulo="Devoluciones", 
        accion="DEVOLUCION_CREADA", 
        descripcion=( 
            f"Devolución '{devolucion.id}' creada " 
            f"para la venta '{venta.folio}' por " 
            f"{usuario.nombre} {usuario.apellido}. " 
            f"Tipo: {devolucion.tipo}. " 
            f"Motivo: {devolucion.motivo}. " 
            f"Total devuelto: " 
            f"${devolucion.total_devuelto:.2f}. " 
            f"Método de reembolso: " 
            f"{metodo_pago_reembolso.nombre}. " 
            f"Estado: PENDIENTE." 
        ), 
    ) 
 
    return devolucion 
 
# ============================================================ 
# ACTUALIZAR DEVOLUCIÓN 
# ============================================================ 
 
@transaction.atomic 
def actualizar_devolucion( 
    devolucion_id, 
    data, 
    usuario 
): 
 
    try: 
 
        devolucion = ( 
            Devolucion.objects 
            .select_for_update() 
            .get(id=devolucion_id) 
        ) 
 
    except Devolucion.DoesNotExist: 
 
        raise BusinessException( 
            "La devolución no existe." 
        ) 
 
    if devolucion.estado != "PENDIENTE": 
 
        raise BusinessException( 
            "Solo se pueden modificar " 
            "devoluciones pendientes." 
        ) 
 
    # ======================================================== 
    # PERMISOS 
    # ======================================================== 
 
    if ( 
        usuario.rol not in (0, 1) 
        and usuario.id != devolucion.usuario_id 
    ): 
 
        raise BusinessException( 
            "No tienes permisos para " 
            "modificar esta devolución." 
        ) 
 
    # ======================================================== 
    # ACTUALIZAR CAMPOS 
    # ======================================================== 
 
    if "tipo" in data:
        nuevo_tipo = data["tipo"]
        
        if nuevo_tipo != devolucion.tipo:
            if nuevo_tipo == "NORMAL":
                venta = (
                    Venta.objects
                    .get(id=devolucion.venta_id)
                )

                _validar_plazo(
                    venta,
                    nuevo_tipo
                )

            elif nuevo_tipo == "GARANTIA":
                _validar_garantia(devolucion)
                
            elif nuevo_tipo == "EXTRAORDINARIA":
                if usuario.rol not in (0, 1):
                    raise BusinessException(
                        "Solo un administrador puede autorizar "
                        "devoluciones extraordinarias."
                    )

            devolucion.tipo = nuevo_tipo
 
    if "motivo" in data: 
 
        devolucion.motivo = data["motivo"] 
 
    if "metodo_pago_reembolso_id" in data: 
 
        try: 
 
            metodo = ( 
                MetodoPago.objects 
                .get( 
                    id=data[ 
                        "metodo_pago_reembolso_id" 
                    ], 
                    activo=True 
                ) 
            ) 
 
        except MetodoPago.DoesNotExist: 
 
            raise BusinessException( 
                "El método de reembolso " 
                "no existe o está inactivo." 
            ) 
 
        devolucion.metodo_pago_reembolso = metodo 
 
    devolucion.save() 
 
    # ======================================================== 
    # BITÁCORA 
    # ======================================================== 
 
    registrar_bitacora( 
        usuario=usuario, 
        modulo="Devoluciones", 
        accion="MODIFICAR_DEVOLUCION", 
        descripcion=( 
            f"Devolución {devolucion.id} " 
            f"modificada para la venta " 
            f"'{devolucion.venta.folio}' por " 
            f"{usuario.nombre} " 
            f"{usuario.apellido}. " 
            f"Motivo: {devolucion.motivo}." 
        ), 
    ) 
 
    return devolucion 
 
def _obtener_corte_efectivo( 
    caja, 
): 
    if not caja.activa: 
        raise BusinessException( 
            "La caja está inactiva y no puede registrar el reembolso." 
        ) 
 
    if caja.estado != Caja.ESTADO_ABIERTA: 
        raise BusinessException( 
            "La caja no se encuentra abierta para registrar el reembolso." 
        ) 
 
    try:
        corte = (
            CorteCaja.objects
            .select_for_update()
            .get(
                caja=caja,
                fecha_fin__isnull=True
            )
        )
    except CorteCaja.DoesNotExist:
        raise BusinessException(
            "La caja no tiene un corte de caja abierto."
        )
    return corte
 
 
# ============================================================ 
# APROBAR DEVOLUCIÓN 
# ============================================================ 

# ============================================================
# APROBAR DEVOLUCIÓN
# ============================================================

# ============================================================
# APROBAR DEVOLUCIÓN
# ============================================================

@transaction.atomic
def aprobar_devolucion(devolucion_id, usuario):
    # ========================================================
    # LECTURAS PRELIMINARES SIN LOCK
    # ========================================================

    try:
        devolucion_base = (
            Devolucion.objects
            .select_related("metodo_pago_reembolso")
            .get(id=devolucion_id)
        )
    except Devolucion.DoesNotExist:
        raise BusinessException(
            "La devolución no existe."
        )

    try:
        venta_base = (
            Venta.objects
            .select_related("corte_caja")
            .get(id=devolucion_base.venta_id)
        )
    except Venta.DoesNotExist:
        raise BusinessException(
            "La venta asociada no existe."
        )

    if not venta_base.corte_caja:
        raise BusinessException(
            "La venta no tiene un corte de caja asociado."
        )

    caja_id = venta_base.corte_caja.caja_id
    corte_id = venta_base.corte_caja_id

    metodo_pago_base = (
        devolucion_base.metodo_pago_reembolso
    )

    # ========================================================
    # LOCK 1: CAJA
    # ========================================================

    caja = (
        Caja.objects
        .select_for_update()
        .get(id=caja_id)
    )

    # ========================================================
    # LOCK 2: CORTE DE CAJA
    # ========================================================

    if (
        metodo_pago_base
        and metodo_pago_base.nombre == "EFECTIVO"
    ):
        # Para efectivo se utiliza el corte abierto
        # de la caja actual.
        corte = _obtener_corte_efectivo(caja)

    else:
        # Para reembolsos no monetarios se conserva
        # el corte asociado a la venta, aunque sea histórico.
        corte = (
            CorteCaja.objects
            .select_for_update()
            .get(
                id=corte_id,
                caja_id=caja_id,
            )
        )

    # ========================================================
    # LOCK 3: VENTA
    # ========================================================

    venta = (
        Venta.objects
        .select_for_update()
        .get(id=devolucion_base.venta_id)
    )

    if not venta.corte_caja:
        raise BusinessException(
            "La venta no tiene un corte de caja asociado."
        )

    # ========================================================
    # LOCK 4: DEVOLUCIÓN
    # ========================================================

    devolucion = (
        Devolucion.objects
        .select_for_update()
        .get(id=devolucion_id)
    )

    # ========================================================
    # VALIDACIONES
    # ========================================================

    if devolucion.estado != "PENDIENTE":
        raise BusinessException(
            "Solo se pueden aprobar devoluciones pendientes."
        )

    if venta.estado == "CANCELADA":
        raise BusinessException(
            "No se puede aprobar una devolución de una venta cancelada."
        )

    if venta.estado == "DEVUELTA":
        raise BusinessException(
            "La venta ya fue devuelta completamente."
        )

    if not devolucion.metodo_pago_reembolso:
        raise BusinessException(
            "La devolución no tiene un método de pago de reembolso."
        )

    metodo_pago = devolucion.metodo_pago_reembolso

    # ========================================================
    # VALIDAR QUE EL MÉTODO NO HAYA CAMBIADO DURANTE
    # LAS LECTURAS PRELIMINARES
    # ========================================================

    metodo_pago_base_id = (
        metodo_pago_base.id
        if metodo_pago_base
        else None
    )

    if metodo_pago.id != metodo_pago_base_id:
        raise BusinessException(
            "La devolución fue modificada durante el proceso. "
            "Intenta nuevamente."
        )

    # ========================================================
    # LOCK 5: DETALLES DE LA VENTA
    # ========================================================

    detalles = list(
        devolucion.detalles.all()
    )

    if not detalles:
        raise BusinessException(
            "La devolución no contiene productos."
        )

    detalle_venta_ids = [
        detalle.detalle_venta_id
        for detalle in detalles
    ]

    detalles_venta = list(
        DetalleVenta.objects
        .select_for_update()
        .filter(
            id__in=detalle_venta_ids,
            venta=venta,
        )
        .order_by("id")
    )

    detalles_venta_map = {
        detalle.id: detalle
        for detalle in detalles_venta
    }

    if (
        len(detalles_venta_map)
        != len(set(detalle_venta_ids))
    ):
        raise BusinessException(
            "Uno o más detalles de la venta no existen."
        )

    # ========================================================
    # VALIDAR CANTIDADES DISPONIBLES
    # ========================================================

    _validar_cantidades_aprobacion(
        detalles,
        devolucion,
    )

    # ========================================================
    # REPONER STOCK
    # ========================================================

    _reponer_stock(
        detalles,
        devolucion,
        usuario,
    )

    # ========================================================
    # REEMBOLSO EN CAJA
    # ========================================================

    if metodo_pago.nombre == "EFECTIVO":
        MovimientoCaja.objects.create(
            corte_caja=corte,
            metodo_pago=metodo_pago,
            tipo="REEMBOLSO",
            monto=devolucion.total_devuelto,
            devolucion=devolucion,
            observaciones=(
                f"Reembolso por devolución "
                f"{devolucion.id}"
            ),
            usuario=usuario,
        )

    devolucion.estado = "APROBADA"

    devolucion.save(
        update_fields=[
            "estado",
        ]
    )

    # ========================================================
    # BITÁCORA
    # ========================================================

    registrar_bitacora(
        usuario=usuario,
        modulo="Devoluciones",
        accion="DEVOLUCION_APROBADA",
        descripcion=(
            f"Devolución '{devolucion.id}' "
            f"aprobada para la venta "
            f"'{venta.folio}' por "
            f"{usuario.nombre} "
            f"{usuario.apellido}. "
            f"Total devuelto: "
            f"${devolucion.total_devuelto:.2f}. "
            f"Método de reembolso: "
            f"{metodo_pago.nombre}. "
            f"Estado: APROBADA."
        ),
    )

    # ========================================================
    # ACTUALIZAR ESTADO DE LA VENTA
    # ========================================================

    if _venta_completamente_devuelta(venta):
        venta.estado = "DEVUELTA"
        venta.save(
            update_fields=["estado"]
        )

    return devolucion


# ============================================================ 
# RECHAZAR DEVOLUCIÓN 
# ============================================================ 
 
@transaction.atomic 
def cambiar_estado_devolucion( 
    devolucion_id, 
    nuevo_estado, 
    usuario 
): 
 
    try: 
 
        devolucion = ( 
            Devolucion.objects 
            .select_for_update() 
            .get(id=devolucion_id) 
        ) 
 
    except Devolucion.DoesNotExist: 
 
        raise BusinessException( 
            "La devolución no existe." 
        ) 
 
    if devolucion.estado != "PENDIENTE": 
 
        raise BusinessException( 
            "Solo se pueden modificar devoluciones pendientes." 
        ) 
 
    if nuevo_estado != "RECHAZADA": 
 
        raise BusinessException( 
            "Para aprobar una devolución debe " 
            "utilizarse el proceso de aprobación." 
        ) 
 
    devolucion.estado = "RECHAZADA" 
 
    devolucion.save( 
        update_fields=[ 
            "estado" 
        ] 
    ) 
 
    registrar_bitacora( 
        usuario=usuario, 
        modulo="Devoluciones", 
        accion="DEVOLUCION_RECHAZADA", 
        descripcion=( 
            f"Devolución '{devolucion.id}' " 
            f"rechazada por " 
            f"{usuario.nombre} " 
            f"{usuario.apellido}. " 
            f"Venta: '{devolucion.venta.folio}'. " 
            f"Motivo registrado: " 
            f"{devolucion.motivo}." 
        ), 
    ) 
 
    return devolucion 
 
def obtener_venta_para_devolucion(folio, usuario): 
    """ 
    Consulta una venta específica para preparar una devolución. 
 
    No bloquea registros porque es una operación de lectura. 
 
    Permisos: 
    - Rol 0: cualquier venta. 
    - Rol 1: cualquier venta. 
    - Rol 2: solamente ventas propias. 
 
    Disponibilidad por detalle: 
        vendido 
        - devoluciones PENDIENTES/APROBADAS 
        - garantías PENDIENTES/APROBADAS/FINALIZADAS 
    """ 
 
    try: 
        venta = ( 
            Venta.objects 
            .select_related("usuario", "metodo_pago") 
            .get(folio=folio) 
        ) 
    except Venta.DoesNotExist: 
        raise BusinessException("La venta no existe.") 
 
    # Empleado solamente puede consultar sus propias ventas. 
    if usuario.rol not in [0, 1] and venta.usuario_id != usuario.id: 
        raise BusinessException( 
            "No tienes permiso para consultar esta venta." 
        ) 
 
    # Una venta cancelada no puede tener devolución. 
    if venta.estado == "CANCELADA": 
        raise BusinessException( 
            "No se puede realizar una devolución de una venta cancelada." 
        ) 
 
    # Una venta completamente devuelta ya no tiene unidades disponibles. 
    if venta.estado == "DEVUELTA": 
        raise BusinessException( 
            "La venta ya fue completamente devuelta." 
        ) 
 
    detalles = list( 
        DetalleVenta.objects 
        .filter(venta_id=venta.id) 
        .select_related("variante__producto") 
        .order_by("id") 
    ) 
 
    detalle_ids = [detalle.id for detalle in detalles] 
 
    # Devoluciones que actualmente consumen disponibilidad. 
    devoluciones = ( 
        DetalleDevolucion.objects 
        .filter( 
            detalle_venta_id__in=detalle_ids, 
            devolucion__estado__in=["PENDIENTE", "APROBADA"], 
        ) 
        .values("detalle_venta_id") 
        .annotate(total=models.Sum("cantidad")) 
    ) 
 
    devoluciones_map = { 
        item["detalle_venta_id"]: item["total"] or 0 
        for item in devoluciones 
    } 
 
    # Garantías que actualmente consumen disponibilidad. 
    garantias = ( 
        Garantia.objects 
        .filter( 
            detalle_venta_id__in=detalle_ids, 
            estado__in=["PENDIENTE", "APROBADA", "FINALIZADA"], 
        ) 
        .values("detalle_venta_id") 
        .annotate(total=models.Sum("cantidad")) 
    ) 
 
    garantias_map = { 
        item["detalle_venta_id"]: item["total"] or 0 
        for item in garantias 
    } 
 
    productos = [] 
 
    for detalle in detalles: 
        devuelto = devoluciones_map.get(detalle.id, 0) 
        en_garantia = garantias_map.get(detalle.id, 0) 
 
        disponible = max( 
            detalle.cantidad - devuelto - en_garantia, 
            0 
        ) 
 
        productos.append({
            "detalle_venta_id": detalle.id,
            "variante_id": detalle.variante_id,
            "producto": detalle.variante.producto.nombre,
            "variante": detalle.variante.nombre,
            "vendido": detalle.cantidad,
            "devuelto": devuelto,
            "en_garantia": en_garantia,
            "disponible_devolucion": disponible,
        })
 
    return { 
        "folio": venta.folio, 
        "fecha": venta.fecha, 
        "usuario": ( 
            f"{venta.usuario.nombre} " 
            f"{venta.usuario.apellido}" 
        ).strip(), 
        "estado": venta.estado, 
        "metodo_pago": venta.metodo_pago.nombre, 
        "productos": productos, 
    }

