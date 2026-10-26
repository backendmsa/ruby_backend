"""Alta transaccional de artículo sencillo sobre el esquema histórico.

No modifica productos antiguos, no inventa SKU y no altera modelos ni tablas.
"""
import uuid

from django.db import IntegrityError, transaction

from categorias.models import Categoria
from categorias.services import crear_categoria
from config.exceptions import BusinessException
from productos.models import Producto
from productos.nombres_articulos import bloquear_nombres_articulos, asegurar_nombre_disponible
from productos.serializers import ProductoSerializer
from productos.services import crear_producto
from variantes.serializers import VarianteSerializer
from variantes.services import crear_variante


CATEGORIA_POR_DEFECTO = "SIN CLASIFICAR"


def _categoria_para_alta(categoria, usuario):
    if categoria is not None:
        if not categoria.activo:
            raise BusinessException("La categoría seleccionada está inactiva.")
        return categoria

    existente = Categoria.objects.filter(nombre__iexact=CATEGORIA_POR_DEFECTO).first()
    if existente is None:
        try:
            # Savepoint: si otro proceso crea la categoría a la vez,
            # podemos recuperar el registro sin abortar toda la transacción.
            with transaction.atomic():
                existente = crear_categoria(
                    validated_data={
                        "nombre": CATEGORIA_POR_DEFECTO,
                        "descripcion": "Artículos pendientes de clasificar.",
                    },
                    usuario=usuario,
                )
        except IntegrityError:
            existente = Categoria.objects.filter(
                nombre__iexact=CATEGORIA_POR_DEFECTO
            ).first()
            if existente is None:
                raise

    if not existente.activo:
        raise BusinessException(
            "La categoría SIN CLASIFICAR está inactiva; debe activarse primero."
        )
    return existente


def _nombre_tecnico_producto(nombre_variante):
    """Conservar nombre visible cuando se pueda; resolver colisión sin tocar variantes.

    Producto.nombre tiene UNIQUE LOWER(nombre) en la BD, pero su valor NO
    es una segunda descripción editable ni se expone en el listado nuevo.
    El sufijo aparece solamente para un nombre de Producto ya ocupado.
    """
    if not Producto.objects.filter(nombre__iexact=nombre_variante).exists():
        return nombre_variante

    for _ in range(5):
        sufijo = f" [art-{uuid.uuid4().hex[:12]}]"
        candidato = nombre_variante[:150 - len(sufijo)] + sufijo
        if not Producto.objects.filter(nombre__iexact=candidato).exists():
            return candidato
    raise BusinessException("No se pudo asignar el identificador interno del artículo.")


@transaction.atomic
def crear_articulo(*, validated_data, usuario):
    """Devuelve su Variante, el único artículo visible de la nueva UI.

    Producto, Variante, stock inicial, bitácora y categoría predeterminada
    se crean en la misma transacción; cualquier error revierte todo.
    """
    datos = dict(validated_data)
    bloquear_nombres_articulos()
    asegurar_nombre_disponible(datos['nombre'])
    categoria = _categoria_para_alta(datos.get("categoria"), usuario)
    nombre_variante = datos["nombre"]
    nombre_producto = _nombre_tecnico_producto(nombre_variante)

    # Reutilizar las validaciones y la bitácora de Producto existentes.
    producto_serializer = ProductoSerializer(data={
        "categoria": str(categoria.pk),
        "nombre": nombre_producto,
    })
    producto_serializer.is_valid(raise_exception=True)
    producto = crear_producto(
        validated_data=dict(producto_serializer.validated_data),
        usuario=usuario,
    )

    # Crear la Variante como única entidad de gestión del empleado.
    # El servicio existente crea stock=0 y luego ENTRADA si stock>0.
    datos_variante = {
        "producto": str(producto.pk),
        "nombre": nombre_variante,
        "sku": datos.get("sku"),
        "codigo_barras": datos.get("codigo_barras"),
        "costo": datos["costo"],
        "precio_menudeo": datos["precio_menudeo"],
        "precio_mayoreo": datos["precio_mayoreo"],
        "stock": datos["stock"],
        "stock_minimo": datos["stock_minimo"],
    }
    variante_serializer = VarianteSerializer(data=datos_variante)
    variante_serializer.is_valid(raise_exception=True)
    return crear_variante(
        validated_data=dict(variante_serializer.validated_data),
        usuario=usuario,
    )
