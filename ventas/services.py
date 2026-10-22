import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import connection, transaction
from django.db.models import Max

from .models import Venta

from detalle_venta.models import DetalleVenta
from variantes.models import Variante
from metodos_pago.models import MetodoPago
from empresa.models import Empresa
from cajas.models import Caja
from corte_caja.models import CorteCaja
from inventario.models import MovimientoInventario

from config.exceptions import BusinessException
from bitacora.services import registrar_bitacora


# ==============================================================
# VALIDACIONES DE ENTRADA
# ==============================================================

def validar_uuid(valor, nombre):
    """
    Convierte y valida un UUID recibido desde la API.
    """

    if valor is None or valor == "":
        raise BusinessException(
            f"Debe indicar {nombre}."
        )

    try:
        return uuid.UUID(str(valor))

    except (
        ValueError,
        TypeError,
        AttributeError,
    ):
        raise BusinessException(
            f"El identificador de {nombre} no es válido."
        )


def validar_descuento(valor):
    """
    Valida y normaliza el descuento de la venta.
    """

    if isinstance(valor, bool):
        raise BusinessException(
            "El descuento debe ser un valor numérico válido."
        )

    if valor is None or valor == "":
        valor = "0"

    try:
        descuento = Decimal(
            str(valor)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        raise BusinessException(
            "El descuento debe ser un valor numérico válido."
        )

    if not descuento.is_finite():
        raise BusinessException(
            "El descuento debe ser un valor válido."
        )

    descuento = descuento.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if descuento < 0:
        raise BusinessException(
            "El descuento no puede ser negativo."
        )

    return descuento


def validar_efectivo_recibido(valor, total, nombre_metodo):
    """Importe opcional para el ticket. Nunca participa en el total de venta.

    Las ventas de otros clientes anteriores pueden omitir el dato.
    Si viene un importe, se exige método de efectivo y precisión de centavos.
    """
    if valor is None:
        return None

    if "efectivo" not in str(nombre_metodo).casefold():
        raise BusinessException(
            "Solo se admite efectivo recibido en pagos en efectivo."
        )
    if isinstance(valor, bool):
        raise BusinessException("El efectivo recibido no es válido.")

    try:
        recibido = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise BusinessException("El efectivo recibido no es válido.")

    if not recibido.is_finite() or recibido < 0:
        raise BusinessException("El efectivo recibido no es válido.")

    if recibido > Decimal("99999999.99"):
        raise BusinessException("El efectivo recibido supera el límite permitido.")

    if recibido != recibido.quantize(Decimal("0.01")):
        raise BusinessException("El efectivo recibido debe tener máximo dos decimales.")

    if recibido < total:
        raise BusinessException("El efectivo recibido es menor que el total de la venta.")

    return recibido.quantize(Decimal("0.01"))


def validar_item_producto(item):
    """
    Valida un producto recibido en la venta.

    Retorna:
        variante_id normalizado como UUID
        cantidad como entero positivo
    """

    if not isinstance(item, dict):
        raise BusinessException(
            "Cada producto debe tener un formato válido."
        )

    variante_id_raw = item.get(
        "variante_id"
    )

    if not variante_id_raw:
        raise BusinessException(
            "Cada producto debe indicar su variante."
        )

    variante_id = validar_uuid(
        variante_id_raw,
        "la variante",
    )

    cantidad_raw = item.get(
        "cantidad"
    )

    if isinstance(
        cantidad_raw,
        bool,
    ):
        raise BusinessException(
            "La cantidad debe ser un número entero."
        )

    if (
        isinstance(cantidad_raw, float)
        and not cantidad_raw.is_integer()
    ):
        raise BusinessException(
            "La cantidad debe ser un número entero."
        )
    
    if isinstance(
        cantidad_raw,
        Decimal,
    ) and not cantidad_raw == cantidad_raw.to_integral_value():
        raise BusinessException(
            "La cantidad debe ser un número entero."
        )
    

    try:
        cantidad = int(
            cantidad_raw
        )

    except (
        TypeError,
        ValueError,
    ):
        raise BusinessException(
            "La cantidad debe ser un número entero."
        )

    if cantidad <= 0:
        raise BusinessException(
            "La cantidad debe ser mayor que cero."
        )

    return variante_id, cantidad


# ==============================================================
# OBTENER RECURSOS
# ==============================================================

def obtener_caja(caja_id):
    """
    Obtiene y bloquea la caja dentro de la transacción.
    """

    caja_id = validar_uuid(
        caja_id,
        "la caja",
    )

    try:
        return (
            Caja.objects
            .select_for_update()
            .get(
                id=caja_id
            )
        )

    except Caja.DoesNotExist:
        raise BusinessException(
            "La caja no existe."
        )


def obtener_metodo_pago(metodo_pago_id):
    """
    Obtiene únicamente métodos de pago activos.
    """

    metodo_pago_id = validar_uuid(
        metodo_pago_id,
        "el método de pago",
    )

    try:
        return (
            MetodoPago.objects
            .get(
                id=metodo_pago_id,
                activo=True,
            )
        )

    except MetodoPago.DoesNotExist:
        raise BusinessException(
            "El método de pago no existe o está inactivo."
        )


def obtener_iva():
    """
    Obtiene y valida el IVA configurado en Empresa.
    """

    empresa = Empresa.objects.first()

    if not empresa:
        raise BusinessException(
            "No hay configuración de empresa."
        )

    try:
        iva = Decimal(
            str(empresa.iva)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        raise BusinessException(
            "El IVA configurado no es válido."
        )

    if not iva.is_finite():
        raise BusinessException(
            "El IVA configurado no es válido."
        )

    if iva < 0 or iva > 100:
        raise BusinessException(
            "El IVA configurado no es válido."
        )

    return iva.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def obtener_corte_abierto(caja):
    """
    Obtiene y bloquea el corte abierto de la caja.
    """

    try:
        return (
            CorteCaja.objects
            .select_for_update()
            .select_related("caja")
            .get(
                caja=caja,
                fecha_fin__isnull=True,
            )
        )

    except CorteCaja.DoesNotExist:
        raise BusinessException(
            "La caja no tiene un corte abierto."
        )


def generar_folio():
    """
    Genera el siguiente folio de venta.

    La concurrencia se controla mediante el advisory lock
    adquirido en crear_venta().
    """

    ultima = (
        Venta.objects
        .aggregate(
            Max("folio")
        )
        ["folio__max"]
    )

    if not ultima:
        numero = 1

    else:

        try:
            partes = ultima.split("-")

            if len(partes) != 2:
                raise ValueError

            if partes[0] != "V":
                raise ValueError

            numero = int(
                partes[1]
            ) + 1

        except (
            IndexError,
            ValueError,
            TypeError,
        ):
            raise BusinessException(
                "No se pudo generar el folio de la venta."
            )

    return f"V-{numero:07d}"


# ==============================================================
# PROCESAR ITEM DE VENTA
# ==============================================================

def procesar_item_venta(
    item,
    venta,
    folio,
    usuario,
    variante,
):
    """
    Procesa un producto de la venta.

    La variante ya debe estar bloqueada con select_for_update().
    """

    variante_id, cantidad = (
        validar_item_producto(item)
    )

    if variante.id != variante_id:
        raise BusinessException(
            "La variante solicitada no coincide con la variante bloqueada."
        )

    if not variante.activo:
        raise BusinessException(
            "La variante está inactiva."
        )

    if not variante.producto.activo:
        raise BusinessException(
            "El producto está inactivo."
        )

    try:
        precio_unitario = Decimal(
            str(variante.precio_menudeo)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        raise BusinessException(
            "El precio del producto no es válido."
        )

    if not precio_unitario.is_finite():
        raise BusinessException(
            "El precio del producto no es válido."
        )

    if precio_unitario < 0:
        raise BusinessException(
            "El precio del producto no puede ser negativo."
        )

    precio_unitario = precio_unitario.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    stock_anterior = variante.stock

    stock_defectuoso_anterior = (
        variante.stock_defectuoso
    )

    if stock_anterior < cantidad:
        raise BusinessException(
            "Stock insuficiente.",
            data={
                "variante_id": str(
                    variante.id
                ),
                "producto": (
                    variante.producto.nombre
                ),
                "variante": (
                    variante.nombre
                ),
                "stock_actual": (
                    stock_anterior
                ),
                "cantidad_solicitada": (
                    cantidad
                ),
            },
        )

    stock_nuevo = (
        stock_anterior - cantidad
    )

    subtotal_linea = (
        precio_unitario * cantidad
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    DetalleVenta.objects.create(
        venta=venta,
        variante=variante,
        cantidad=cantidad,
        precio_unitario=precio_unitario,
        descuento=Decimal("0.00"),
        subtotal=subtotal_linea,
    )

    MovimientoInventario.objects.create(
        variante=variante,
        tipo="SALIDA",
        stock_anterior=stock_anterior,
        cantidad=cantidad,
        stock_nuevo=stock_nuevo,
        stock_defectuoso_anterior=(
            stock_defectuoso_anterior
        ),
        stock_defectuoso_nuevo=(
            stock_defectuoso_anterior
        ),
        observaciones=(
            f"Venta {folio}"
        ),
        usuario=usuario,
    )

    variante.stock = stock_nuevo

    variante.save(
        update_fields=[
            "stock",
            "fecha_actualizacion",
        ]
    )

    return subtotal_linea


# ==============================================================
# CREAR VENTA
# ==============================================================


    
@transaction.atomic
def crear_venta(
    data,
    usuario,
):
    """
    Crea una venta completa.

    Orden de bloqueo:

        Caja
          ↓
        CorteCaja
          ↓
        Variante(s)
          ↓
        Advisory lock de folio
          ↓
        Venta
          ↓
        DetalleVenta
          ↓
        MovimientoInventario
    """
    
    if not usuario.activo:
        raise BusinessException(
            "El usuario está inactivo."
        )
    
    if not hasattr(data, "get"):
        raise BusinessException(
            "El cuerpo de la venta debe tener un formato válido."
        )


    caja_id_raw = data.get(
        "caja_id"
    )

    metodo_pago_id_raw = data.get(
        "metodo_pago_id"
    )

    productos = data.get(
        "productos",
        [],
    )

    # ----------------------------------------------------------
    # VALIDAR CAMPOS PRINCIPALES
    # ----------------------------------------------------------

    caja_id = validar_uuid(
        caja_id_raw,
        "la caja",
    )

    metodo_pago_id = validar_uuid(
        metodo_pago_id_raw,
        "el método de pago",
    )

    if not isinstance(
        productos,
        list,
    ) or not productos:
        raise BusinessException(
            "Debe agregar al menos un producto."
        )

    # ----------------------------------------------------------
    # VALIDAR PRODUCTOS
    #
    # Aquí todavía NO bloqueamos variantes.
    # ----------------------------------------------------------

    items_validados = []
    variantes_recibidas = set()

    for item in productos:
        variante_id, cantidad = validar_item_producto(item)
        
        if variante_id in variantes_recibidas:
            raise BusinessException(
                "No se pueden repetir variantes en una misma venta."
            )
        variantes_recibidas.add(variante_id)
        
        items_validados.append(
            (
                variante_id,
                cantidad,
        )
    )
    
    descuento = validar_descuento(
        data.get(
            "descuento",
            "0",
        )
    )

    # ----------------------------------------------------------
    # LOCK 1: CAJA
    #
    # Se bloquea antes de comprobar estado para evitar
    # carreras entre venta y cierre/desactivación.
    # ----------------------------------------------------------

    caja = obtener_caja(
        caja_id
    )

    if not caja.activa:
        raise BusinessException(
            "La caja está inactiva."
        )

    if caja.estado != Caja.ESTADO_ABIERTA:
        raise BusinessException(
            "La caja está cerrada."
        )

    # ----------------------------------------------------------
    # MÉTODO DE PAGO
    # ----------------------------------------------------------

    metodo_pago = obtener_metodo_pago(
        metodo_pago_id
    )

    # ----------------------------------------------------------
    # IVA
    # ----------------------------------------------------------

    iva_porcentaje = obtener_iva()


    corte = obtener_corte_abierto(
        caja
    )

    # ----------------------------------------------------------
    # VALIDAR PROPIETARIO DEL CORTE
    #
    # Se valida antes de bloquear variantes para evitar
    # adquirir locks innecesarios.
    # ----------------------------------------------------------

    if corte.usuario_id != usuario.id:
        raise BusinessException(
            "Esta caja está siendo utilizada por otro empleado."
        )

    # ==========================================================
    # LOCK 3: TODAS LAS VARIANTES
    #
    # Se bloquean:
    #
    #   - únicamente una vez por variante
    #   - en orden determinístico
    #
    # Esto evita carreras sobre el último stock disponible.
    # ==========================================================

    variante_ids = sorted(
        {
            variante_id
            for variante_id, _ in items_validados
        },
        key=str,
    )

    variantes = list(
        Variante.objects
        .select_for_update()
        .select_related("producto")
        .filter(
            id__in=variante_ids
        )
        .order_by("id")
    )

    variantes_map = {
        variante.id: variante
        for variante in variantes
    }

    if len(variantes_map) != len(
        variante_ids
    ):
        raise BusinessException(
            "Una o más variantes no existen."
        )
        
    with connection.cursor() as cursor:

        cursor.execute(
            """
            SELECT pg_advisory_xact_lock(
                hashtext('ventas_folio')
            )
            """
        )

    # ----------------------------------------------------------
    # FOLIO
    # ----------------------------------------------------------

    folio = generar_folio()

    # ----------------------------------------------------------
    # CREAR VENTA
    # ----------------------------------------------------------

    venta = Venta.objects.create(
        folio=folio,
        usuario=usuario,
        corte_caja=corte,
        metodo_pago=metodo_pago,
        subtotal=Decimal("0.00"),
        descuento=descuento,
        iva=Decimal("0.00"),
        total=Decimal("0.00"),
    )

    subtotal = Decimal(
        "0.00"
    )

    # ----------------------------------------------------------
    # PROCESAR PRODUCTOS
    # ----------------------------------------------------------

    for variante_id, cantidad in (
        items_validados
    ):

        variante = variantes_map.get(
            variante_id
        )

        if not variante:
            raise BusinessException(
                "La variante no existe."
            )

        subtotal += procesar_item_venta(
            item={
                "variante_id": variante_id,
                "cantidad": cantidad,
            },
            venta=venta,
            folio=folio,
            usuario=usuario,
            variante=variante,
        )

    # ----------------------------------------------------------
    # VALIDAR SUBTOTAL
    # ----------------------------------------------------------

    subtotal = subtotal.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if subtotal <= 0:
        raise BusinessException(
            "El subtotal de la venta debe ser mayor que cero."
        )

    # ----------------------------------------------------------
    # VALIDAR DESCUENTO
    # ----------------------------------------------------------

    if descuento > subtotal:
        raise BusinessException(
            "El descuento no puede ser mayor al subtotal."
        )

    # ----------------------------------------------------------
    # CALCULAR SUBTOTAL FINAL
    # ----------------------------------------------------------

    subtotal_final = (
        subtotal - descuento
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # ----------------------------------------------------------
    # CALCULAR IVA
    # ----------------------------------------------------------

    iva = (
        subtotal_final
        * (
            iva_porcentaje
            / Decimal("100")
        )
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # ----------------------------------------------------------
    # CALCULAR TOTAL
    # ----------------------------------------------------------

    total = (
        subtotal_final + iva
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # ----------------------------------------------------------
    # EFECTIVO RECIBIDO (OPCIONAL / COMPATIBLE)
    # ----------------------------------------------------------
    # Se valida con el TOTAL REAL calculado en backend, antes del commit.
    # No afecta el total vendido, IVA, descuento, inventario ni corte.
    efectivo_recibido = validar_efectivo_recibido(
        data.get("efectivo_recibido"),
        total,
        metodo_pago.nombre,
    )

    # ----------------------------------------------------------
    # ACTUALIZAR VENTA
    # ----------------------------------------------------------

    venta.efectivo_recibido = efectivo_recibido
    venta.subtotal = subtotal_final
    venta.descuento = descuento
    venta.iva = iva
    venta.total = total

    venta.save(
        update_fields=[
            "subtotal",
            "descuento",
            "iva",
            "total",
            "efectivo_recibido",
        ]
    )

    # ----------------------------------------------------------
    # BITÁCORA
    # ----------------------------------------------------------

    registrar_bitacora(
        usuario=usuario,
        modulo="Ventas",
        accion="REGISTRAR_VENTA",
        descripcion=(
            f"Venta folio {venta.folio} "
            f"registrada correctamente por "
            f"{usuario.nombre} "
            f"{usuario.apellido}. "
            f"Total: ${venta.total:.2f}"
        ),
    )

    return venta


# ==============================================================
# CANCELAR VENTA
# ==============================================================

@transaction.atomic
def cancelar_venta(
    venta_id,
    usuario,
):
    """
    Cancela una venta y restaura su inventario.

    Orden de bloqueo:

        Caja
          ↓
        CorteCaja
          ↓
        Venta
          ↓
        Variante(s)
          ↓
        MovimientoInventario

    La cancelación NO genera movimiento de caja.
    """

    # ----------------------------------------------------------
    # VALIDAR USUARIO
    # ----------------------------------------------------------

    if not usuario.activo:
        raise BusinessException(
            "El usuario está inactivo."
        )

    # ----------------------------------------------------------
    # VALIDAR UUID DE VENTA
    # ----------------------------------------------------------

    venta_id = validar_uuid(
        venta_id,
        "la venta",
    )

    # ==========================================================
    # OBTENER VENTA PARA DESCUBRIR CAJA Y CORTE
    # ==========================================================

    try:

        venta_base = (
            Venta.objects
            .select_related(
                "corte_caja"
            )
            .get(
                id=venta_id
            )
        )

    except Venta.DoesNotExist:

        raise BusinessException(
            "La venta no existe."
        )

    caja_id = (
        venta_base
        .corte_caja
        .caja_id
    )

    corte_id = (
        venta_base
        .corte_caja_id
    )

    # ==========================================================
    # LOCK 1: CAJA
    # ==========================================================

    try:

        caja = (
            Caja.objects
            .select_for_update()
            .get(
                id=caja_id
            )
        )

    except Caja.DoesNotExist:

        raise BusinessException(
            "La caja asociada a la venta no existe."
        )

    # ==========================================================
    # LOCK 2: CORTE
    # ==========================================================

    try:

        corte = (
            CorteCaja.objects
            .select_for_update()
            .get(
                id=corte_id,
                caja=caja,
            )
        )

    except CorteCaja.DoesNotExist:

        raise BusinessException(
            "El corte de caja asociado a la venta no existe."
        )

    # ==========================================================
    # LOCK 3: VENTA
    # ==========================================================

    try:

        venta = (
            Venta.objects
            .select_for_update()
            .get(
                id=venta_id
            )
        )

    except Venta.DoesNotExist:

        raise BusinessException(
            "La venta no existe."
        )

    # ----------------------------------------------------------
    # VALIDAR PROPIETARIO
    # ----------------------------------------------------------

    if (
        usuario.rol not in (0, 1)
        and venta.usuario_id != usuario.id
    ):
        raise BusinessException(
            "Solo puedes cancelar tus propias ventas."
        )

    # ----------------------------------------------------------
    # VALIDAR ESTADO
    # ----------------------------------------------------------

    if venta.estado == "CANCELADA":
        raise BusinessException(
            "La venta ya está cancelada."
        )

    if venta.estado == "DEVUELTA":
        raise BusinessException(
            "No se puede cancelar una venta que ya fue devuelta completamente."
        )

    # ----------------------------------------------------------
    # VALIDAR CORTE
    # ----------------------------------------------------------

    if corte.fecha_fin is not None:
        raise BusinessException(
            "No se puede cancelar la venta porque el corte de caja ya está cerrado."
        )

    # ----------------------------------------------------------
    # VALIDAR DEVOLUCIONES Y GARANTÍAS
    # ----------------------------------------------------------

    from devoluciones.models import Devolucion
    from garantias.models import Garantia

    if Devolucion.objects.filter(
        venta=venta,
        estado__in=[
            "PENDIENTE",
            "APROBADA",
        ],
    ).exists():

        raise BusinessException(
            "No se puede cancelar la venta porque tiene una devolución pendiente o aprobada."
        )

    if Garantia.objects.filter(
        venta=venta,
        estado__in=[
            "PENDIENTE",
            "APROBADA",
            "FINALIZADA",
        ],
    ).exists():

        raise BusinessException(
            "No se puede cancelar la venta porque tiene una garantía pendiente, aprobada o finalizada."
        )

    # ==========================================================
    # OBTENER DETALLES
    #
    # Se ordenan por variante_id para que el bloqueo de variantes
    # sea determinístico.
    # ==========================================================

    detalles = list(
        venta.detalles
        .order_by(
            "variante_id",
            "id",
        )
    )

    # ==========================================================
    # BLOQUEAR Y RESTAURAR VARIANTES
    # ==========================================================

    variante_ids = sorted(
        {
            detalle.variante_id
            for detalle in detalles
        },
        key=str,
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
    
    if len(variantes_map) != len(
        variante_ids
    ):
        raise BusinessException(
            "Una o más variantes no existen."
        )
        
    for detalle in detalles:
        
        variante = variantes_map.get(
            detalle.variante_id
        )
        
        if not variante:
            raise BusinessException(
                "La variante de la venta no existe."
            )


        stock_anterior = (
            variante.stock
        )

        stock_nuevo = (
            stock_anterior
            + detalle.cantidad
        )

        stock_defectuoso_anterior = (
            variante.stock_defectuoso
        )

        # ------------------------------------------------------
        # MOVIMIENTO DE INVENTARIO
        # ------------------------------------------------------

        MovimientoInventario.objects.create(
            variante=variante,
            tipo="ENTRADA",
            stock_anterior=stock_anterior,
            cantidad=detalle.cantidad,
            stock_nuevo=stock_nuevo,
            stock_defectuoso_anterior=(
                stock_defectuoso_anterior
            ),
            stock_defectuoso_nuevo=(
                stock_defectuoso_anterior
            ),
            observaciones=(
                f"Cancelación {venta.folio}"
            ),
            usuario=usuario,
        )

        # ------------------------------------------------------
        # RESTAURAR STOCK
        # ------------------------------------------------------

        variante.stock = stock_nuevo

        variante.save(
            update_fields=[
                "stock",
                "fecha_actualizacion",
            ]
        )

    # ==========================================================
    # CAMBIAR ESTADO DE LA VENTA
    # ==========================================================

    venta.estado = "CANCELADA"

    venta.save(
        update_fields=[
            "estado",
        ]
    )

    # ==========================================================
    # BITÁCORA
    # ==========================================================

    registrar_bitacora(
        usuario=usuario,
        modulo="Ventas",
        accion="CANCELAR_VENTA",
        descripcion=(
            f"Venta folio {venta.folio} "
            f"cancelada correctamente por "
            f"{usuario.nombre} "
            f"{usuario.apellido}. "
            f"Se restauró el stock de los productos."
        ),
    )

    return venta