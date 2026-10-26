"""Nombre completo de gestión, compatible con artículos históricos.

La variante conserva su vínculo y nombre de presentación históricos; cuando se
renombra por completo una presentación compartida, se guarda un nombre visible
independiente sin renombrar a sus hermanas ni perder claves foráneas.
"""
import re
import unicodedata
from django.db import connection
from variantes.models import Variante
from config.exceptions import BusinessException


def normalizar_nombre(nombre):
    return unicodedata.normalize('NFKC', ' '.join(str(nombre).split())).casefold()


def nombre_visible(variante):
    if variante.nombre_completo:
        return variante.nombre_completo.strip()

    nombre_variante = variante.nombre.strip()
    nombre_producto = variante.producto.nombre.strip()
    if not nombre_producto or nombre_producto.casefold() == nombre_variante.casefold():
        return nombre_variante
    if re.fullmatch(r'.* \[art-[0-9a-f]{12}\]', nombre_producto):
        return nombre_variante
    if nombre_variante.casefold() in {'unica', 'única', 'unico', 'único'}:
        return nombre_producto
    return f'{nombre_producto} - {nombre_variante}'


def bloquear_nombres_articulos():
    """Bloqueo de transacción PostgreSQL para evitar altas/ediciones simultáneas."""
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT pg_advisory_xact_lock(hashtext(%s))',
            ['belleza:nombres_visibles_articulos'],
        )


def asegurar_nombre_disponible(nombre, *, excluir_pk=None):
    objetivo = normalizar_nombre(nombre)
    consulta = Variante.objects.select_related('producto').only(
        'id', 'nombre', 'nombre_completo', 'producto__nombre'
    )
    if excluir_pk is not None:
        consulta = consulta.exclude(pk=excluir_pk)
    # Incluye activos, inactivos, históricos y artículos nuevos.
    for variante in consulta.iterator(chunk_size=500):
        if normalizar_nombre(nombre_visible(variante)) == objetivo:
            raise BusinessException(
                'Ya existe un artículo con ese nombre. Búscalo en el catálogo y edítalo.'
            )
