import logging
import uuid
from rest_framework.pagination import PageNumberPagination

from django.db.models import F, Q
from django.utils.dateparse import parse_date
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import MovimientoInventario
from .serializers import MovimientoInventarioSerializer
from .services import (
    registrar_entrada,
    registrar_salida,
    registrar_ajuste,
)

from variantes.models import Variante
from config.exceptions import BusinessException


logger = logging.getLogger(__name__)

class MovimientoInventarioPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    
    
class MovimientoInventarioViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        MovimientoInventario.objects
        .select_related(
            "variante",
            "variante__producto",
            "usuario",
        )
        .all()
        .order_by("-fecha")
    )

    serializer_class = MovimientoInventarioSerializer
    pagination_class = MovimientoInventarioPagination
    permission_classes = [IsAuthenticated]

    # ==========================================================
    # FILTROS DEL HISTORIAL
    # ==========================================================

    def get_queryset(self):

        queryset = super().get_queryset()

        tipo = self.request.query_params.get("tipo")
        variante_id = self.request.query_params.get(
            "variante_id"
        )
        search = self.request.query_params.get("search")
        fecha_desde_raw = self.request.query_params.get(
            "fecha_desde"
        )
        fecha_hasta_raw = self.request.query_params.get(
            "fecha_hasta"
        )

        # ------------------------------------------------------
        # VALIDAR TIPO
        # ------------------------------------------------------

        if tipo is not None:

            tipo = tipo.strip().upper()

            tipos_validos = {
                tipo_movimiento
                for tipo_movimiento, _
                in MovimientoInventario.TIPOS
            }

            if tipo not in tipos_validos:

                raise BusinessException(
                    "El tipo de movimiento no es válido.",
                    data={
                        "tipo_recibido": tipo,
                        "tipos_validos": sorted(
                            tipos_validos
                        ),
                    },
                )

            queryset = queryset.filter(
                tipo=tipo
            )

        # ------------------------------------------------------
        # VALIDAR VARIANTE_ID
        # ------------------------------------------------------

        if variante_id is not None:

            variante_id = variante_id.strip()

            try:
                variante_uuid = uuid.UUID(
                    variante_id
                )

            except (
                ValueError,
                AttributeError,
            ):

                raise BusinessException(
                    "El identificador de la variante "
                    "no es válido."
                )

            if not Variante.objects.filter(
                id=variante_uuid
            ).exists():

                raise BusinessException(
                    "La variante no existe."
                )

            queryset = queryset.filter(
                variante_id=variante_uuid
            )

        # ------------------------------------------------------
        # VALIDAR BÚSQUEDA
        # ------------------------------------------------------

        if search is not None:

            search = search.strip()

            if len(search) > 100:

                raise BusinessException(
                    "El texto de búsqueda no puede "
                    "superar los 100 caracteres."
                )

            if search:

                queryset = queryset.filter(
                    Q(
                        variante__nombre__icontains=search
                    )
                    | Q(
                        variante__producto__nombre__icontains=search
                    )
                    | Q(
                        variante__sku__icontains=search
                    )
                    | Q(
                        variante__codigo_barras__icontains=search
                    )
                    | Q(
                        observaciones__icontains=search
                    )
                )

        # ------------------------------------------------------
        # VALIDAR FECHAS
        # ------------------------------------------------------

        fecha_desde = (
            parse_date(fecha_desde_raw)
            if fecha_desde_raw
            else None
        )

        fecha_hasta = (
            parse_date(fecha_hasta_raw)
            if fecha_hasta_raw
            else None
        )

        if (
            fecha_desde_raw
            and fecha_desde is None
        ):

            raise BusinessException(
                "La fecha inicial debe tener "
                "formato YYYY-MM-DD."
            )

        if (
            fecha_hasta_raw
            and fecha_hasta is None
        ):

            raise BusinessException(
                "La fecha final debe tener "
                "formato YYYY-MM-DD."
            )

        if (
            fecha_desde
            and fecha_hasta
            and fecha_desde > fecha_hasta
        ):

            raise BusinessException(
                "La fecha final no puede ser "
                "anterior a la fecha inicial."
            )

        if fecha_desde:

            queryset = queryset.filter(
                fecha__date__gte=fecha_desde
            )

        if fecha_hasta:

            queryset = queryset.filter(
                fecha__date__lte=fecha_hasta
            )

        return queryset

    # ==========================================================
    # ENTRADA
    # ==========================================================

    @action(
        detail=False,
        methods=["post"],
    )
    def entrada(self, request):

        try:

            (
                movimiento,
                stock_anterior,
                stock_nuevo,
                stock_defectuoso_anterior,
                stock_defectuoso_nuevo,
            ) = registrar_entrada(
                variante_id=request.data.get(
                    "variante_id"
                ),
                cantidad=request.data.get(
                    "cantidad"
                ),
                observaciones=request.data.get(
                    "observaciones"
                ),
                usuario=request.user,
            )

        except BusinessException as e:

            return Response(
                {
                    "success": False,
                    "message": str(e),
                    "data": e.data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception:

            logger.exception(
                "Error inesperado en entrada de inventario"
            )

            return Response(
                {
                    "success": False,
                    "message": "Error interno del servidor.",
                    "data": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Movimiento de inventario "
                    "registrado correctamente."
                ),
                "data": {
                    "id": movimiento.id,
                    "tipo": movimiento.tipo,
                    "stock_anterior": stock_anterior,
                    "cantidad": movimiento.cantidad,
                    "stock_nuevo": stock_nuevo,
                    "stock_defectuoso_anterior": (
                        stock_defectuoso_anterior
                    ),
                    "stock_defectuoso_nuevo": (
                        stock_defectuoso_nuevo
                    ),
                },
            },
            status=status.HTTP_201_CREATED,
        )

    # ==========================================================
    # SALIDA
    # ==========================================================

    @action(
        detail=False,
        methods=["post"],
    )
    def salida(self, request):

        try:

            (
                movimiento,
                stock_anterior,
                stock_nuevo,
                stock_defectuoso_anterior,
                stock_defectuoso_nuevo,
            ) = registrar_salida(
                variante_id=request.data.get(
                    "variante_id"
                ),
                cantidad=request.data.get(
                    "cantidad"
                ),
                observaciones=request.data.get(
                    "observaciones"
                ),
                usuario=request.user,
            )

        except BusinessException as e:

            return Response(
                {
                    "success": False,
                    "message": str(e),
                    "data": e.data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception:

            logger.exception(
                "Error inesperado en salida de inventario"
            )

            return Response(
                {
                    "success": False,
                    "message": "Error interno del servidor.",
                    "data": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Movimiento de inventario "
                    "registrado correctamente."
                ),
                "data": {
                    "id": movimiento.id,
                    "tipo": movimiento.tipo,
                    "stock_anterior": stock_anterior,
                    "cantidad": movimiento.cantidad,
                    "stock_nuevo": stock_nuevo,
                    "stock_defectuoso_anterior": (
                        stock_defectuoso_anterior
                    ),
                    "stock_defectuoso_nuevo": (
                        stock_defectuoso_nuevo
                    ),
                },
            },
            status=status.HTTP_201_CREATED,
        )

    # ==========================================================
    # AJUSTE
    # ==========================================================

    @action(
        detail=False,
        methods=["post"],
    )
    def ajuste(self, request):

        try:

            (
                movimiento,
                stock_anterior,
                stock_nuevo,
                stock_defectuoso_anterior,
                stock_defectuoso_nuevo,
                tipo_ajuste,
            ) = registrar_ajuste(
                variante_id=request.data.get(
                    "variante_id"
                ),
                stock_nuevo_solicitado=request.data.get(
                    "stock_nuevo"
                ),
                observaciones=request.data.get(
                    "observaciones"
                ),
                usuario=request.user,
            )

        except BusinessException as e:

            return Response(
                {
                    "success": False,
                    "message": str(e),
                    "data": e.data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception:

            logger.exception(
                "Error inesperado en ajuste de inventario"
            )

            return Response(
                {
                    "success": False,
                    "message": "Error interno del servidor.",
                    "data": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Ajuste de inventario "
                    "registrado correctamente."
                ),
                "data": {
                    "id": movimiento.id,
                    "tipo": movimiento.tipo,
                    "stock_anterior": stock_anterior,
                    "cantidad": movimiento.cantidad,
                    "stock_nuevo": stock_nuevo,
                    "stock_defectuoso_anterior": (
                        stock_defectuoso_anterior
                    ),
                    "stock_defectuoso_nuevo": (
                        stock_defectuoso_nuevo
                    ),
                    "tipo_ajuste": tipo_ajuste,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    # ==========================================================
    # BAJO STOCK
    # ==========================================================

    @action(
        detail=False,
        methods=["get"],
        url_path="bajo-stock",
    )
    def bajo_stock(self, request):

        variantes = (
            Variante.objects
            .filter(
                activo=True,
                stock__lte=F("stock_minimo"),
            )
            .select_related(
                "producto",
                "producto__categoria",
            )
            .order_by(
                "stock",
                "producto__nombre",
                "nombre",
            )
        )

        data = [
            {
                "variante_id": variante.id,
                "producto": variante.producto.nombre,
                "variante": variante.nombre,
                "stock": variante.stock,
                "stock_minimo": variante.stock_minimo,
            }
            for variante in variantes
        ]

        return Response(
            {
                "success": True,
                "message": (
                    "Variantes con bajo stock "
                    "obtenidas correctamente."
                ),
                "data": data,
            },
            status=status.HTTP_200_OK,
        )