from django.db import IntegrityError
from django.db.models import Q, CharField, Value
from django.db.models.functions import Concat

from rest_framework.exceptions import ValidationError

from variantes.models import Variante
from .articulos import crear_articulo
from productos.nombres_articulos import nombre_visible
from .serializers_articulos import (
    ArticuloGestionSerializer,
    RegistroArticuloSerializer,
)

from rest_framework import (
    viewsets,
    status,
)

from rest_framework.response import Response

from rest_framework.permissions import (
    IsAuthenticated,
)

from rest_framework.decorators import action

from rest_framework.pagination import PageNumberPagination

from .models import Producto

from .serializers import (
    ProductoSerializer,
)

from .services import (
    crear_producto,
    actualizar_producto,
    activar_producto,
    desactivar_producto,
)

from usuarios.permissions import (
    IsAdmin,
)

from config.exceptions import BusinessException


class ProductoPagination(
    PageNumberPagination
):

    page_size = 50

    page_size_query_param = "page_size"

    max_page_size = 200


class ProductoViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        Producto.objects
        .filter(activo=True)
        .select_related("categoria")
    )

    serializer_class = ProductoSerializer

    pagination_class = ProductoPagination

    # ==========================================================
    # SIN DELETE
    # ==========================================================

    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "head",
        "options",
    ]

    # ==========================================================
    # QUERYSET
    # ==========================================================

    def get_queryset(self):

        user = self.request.user

        es_admin = (
            user
            and user.is_authenticated
            and getattr(user, "activo", False)
            and user.rol in (0, 1)
        )

        if self.action in [
            "update",
            "partial_update",
            "activar",
            "desactivar",
        ]:

            return (
                Producto.objects
                .all()
                .select_related("categoria")
            )

        if (
            self.action == "retrieve"
            and es_admin
        ):

            return (
                Producto.objects
                .all()
                .select_related("categoria")
            )

        search = (
            self.request.query_params.get(
                "search",
                "",
            )
            .strip()
        )

        if (
            self.action == "list"
            and es_admin
        ):

            activo_param = (
                self.request.query_params.get(
                    "activo"
                )
            )

            if activo_param is not None:

                if activo_param.lower() == "todos":

                    queryset = Producto.objects.all()

                else:

                    queryset = Producto.objects.filter(
                        activo=(
                            activo_param.lower()
                            in ("true", "1")
                        )
                    )

            else:

                queryset = Producto.objects.filter(
                    activo=True
                )

        else:

            queryset = Producto.objects.filter(
                activo=True
            )

        if (
            self.action == "list"
            and search
        ):

            queryset = queryset.filter(
                Q(nombre__icontains=search)
                | Q(categoria__nombre__icontains=search)
                | Q(variantes__nombre__icontains=search)
                | Q(variantes__sku__icontains=search)
                | Q(
                    variantes__codigo_barras__icontains=search
                )
            ).distinct()

        return (
            queryset
            .select_related("categoria")
            .order_by(
                "nombre",
                "id",
            )
        )

    # ==========================================================
    # PERMISOS
    # ==========================================================

    def get_permissions(self):
        if self.action in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
        ]:
            return [
                IsAuthenticated(),
            ]

        if self.action in [
            "activar",
            "desactivar",
        ]:
            return [
                IsAuthenticated(),
                IsAdmin(),
            ]

        return [
            IsAuthenticated(),
        ]

    # ==========================================================
    # CREAR
    # ==========================================================

    def create(
        self,
        request,
        *args,
        **kwargs,
    ):

        serializer = self.get_serializer(
            data=request.data
        )

        if not serializer.is_valid():

            return Response(
                {
                    "success": False,
                    "message": (
                        "No se pudo registrar "
                        "el producto."
                    ),
                    "data": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:

            producto = crear_producto(
                validated_data=(
                    serializer.validated_data
                ),
                usuario=request.user,
            )

        except BusinessException as exc:

            return Response(
                {
                    "success": False,
                    "message": str(exc),
                    "data": None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except IntegrityError:

            return Response(
                {
                    "success": False,
                    "message": (
                        "Ya existe un producto "
                        "con este nombre."
                    ),
                    "data": None,
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer.instance = producto

        return Response(
            {
                "success": True,
                "message": (
                    "Producto registrado "
                    "correctamente."
                ),
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    # ==========================================================
    # REGISTRO UNIFICADO: SOLO NOMBRE DE VARIANTE VISIBLE
    # ==========================================================

    @action(detail=False, methods=["post"], url_path="registro-completo")
    def registro_completo(self, request):
        serializer = RegistroArticuloSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "message": "No se pudo registrar el artículo.",
                 "data": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            variante = crear_articulo(
                validated_data=serializer.validated_data, usuario=request.user,
            )
        except ValidationError as exc:
            return Response(
                {"success": False, "message": "No se pudo registrar el artículo.",
                 "data": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except BusinessException as exc:
            return Response(
                {"success": False, "message": str(exc), "data": None},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IntegrityError:
            return Response(
                {"success": False,
                 "message": "Conflicto de datos: el artículo no pudo registrarse. Intenta nuevamente.",
                 "data": None},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {"success": True, "message": "Artículo registrado correctamente.",
             "data": ArticuloGestionSerializer(variante).data},
            status=status.HTTP_201_CREATED,
        )

    # ==========================================================
    # GESTIÓN: UNA FILA POR VARIANTE, NOMBRE = Variante.nombre
    # ==========================================================

    @action(detail=False, methods=["get"], url_path="articulos")
    def articulos(self, request):
        queryset = Variante.objects.select_related("producto", "producto__categoria")
        # Empleados activos también deben encontrar y recuperar artículos inactivos.
        es_gestor = (getattr(request.user, "activo", False)
                     and getattr(request.user, "rol", None) in (0, 1, 2))

        if es_gestor:
            activo = request.query_params.get("activo", "true").lower()
            if activo not in ("true", "1", "false", "0", "todos"):
                raise ValidationError({"activo": "Usa true, false o todos."})
            if activo != "todos":
                queryset = queryset.filter(activo=activo in ("true", "1"))
        else:
            queryset = queryset.filter(activo=True, producto__activo=True)

        busqueda = request.query_params.get("search", "").strip()
        if len(busqueda) > 100:
            raise ValidationError({"search": "La búsqueda no puede superar 100 caracteres."})
        if busqueda:
            queryset = queryset.alias(
                _nombre_completo_busqueda=Concat(
                    "producto__nombre", Value(" - "), "nombre",
                    output_field=CharField(),
                )
            )
            queryset = queryset.filter(
                Q(nombre__icontains=busqueda)
                | Q(nombre_completo__icontains=busqueda)
                | Q(sku__icontains=busqueda)
                | Q(codigo_barras__icontains=busqueda)
                | Q(producto__nombre__icontains=busqueda)
                | Q(_nombre_completo_busqueda__icontains=busqueda)
                | Q(producto__categoria__nombre__icontains=busqueda)
            )

        categoria_id = request.query_params.get("categoria")
        if categoria_id:
            import uuid
            try:
                categoria_uuid = uuid.UUID(categoria_id)
            except (TypeError, ValueError, AttributeError):
                raise ValidationError({"categoria": "El ID de categoría no es válido."})
            queryset = queryset.filter(producto__categoria_id=categoria_uuid)

        queryset = queryset.order_by("nombre", "id")
        pagina = self.paginate_queryset(queryset)
        if pagina is not None:
            return self.get_paginated_response(
                ArticuloGestionSerializer(pagina, many=True).data
            )
        return Response(ArticuloGestionSerializer(queryset, many=True).data)

    # ==========================================================
    # MODIFICAR
    # ==========================================================

    def update(
        self,
        request,
        *args,
        **kwargs,
    ):

        partial = kwargs.pop(
            "partial",
            False,
        )

        instancia = self.get_object()

        serializer = self.get_serializer(
            instancia,
            data=request.data,
            partial=partial,
        )

        if not serializer.is_valid():

            return Response(
                {
                    "success": False,
                    "message": (
                        "No se pudo modificar "
                        "el producto."
                    ),
                    "data": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:

            producto = actualizar_producto(
                instancia=instancia,
                validated_data=(
                    serializer.validated_data
                ),
                usuario=request.user,
            )

        except BusinessException as exc:

            return Response(
                {
                    "success": False,
                    "message": str(exc),
                    "data": None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except IntegrityError:

            return Response(
                {
                    "success": False,
                    "message": (
                        "Ya existe un producto "
                        "con este nombre."
                    ),
                    "data": None,
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer.instance = producto

        return Response(
            {
                "success": True,
                "message": (
                    "Producto modificado "
                    "correctamente."
                ),
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    # ==========================================================
    # ACTIVAR
    # ==========================================================

    @action(
        detail=True,
        methods=["post"],
        url_path="activar",
    )
    def activar(
        self,
        request,
        pk=None,
    ):

        try:

            producto = activar_producto(
                producto_id=pk,
                usuario=request.user,
            )


        except BusinessException as exc:

            return Response(
                {
                    "success": False,
                    "message": str(exc),
                    "data": None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Producto activado "
                    "correctamente."
                ),
                "data": ProductoSerializer(
                    producto
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    # ==========================================================
    # DESACTIVAR
    # ==========================================================

    @action(
        detail=True,
        methods=["post"],
        url_path="desactivar",
    )
    def desactivar(
        self,
        request,
        pk=None,
    ):

        try:

            producto = desactivar_producto(
                producto_id=pk,
                usuario=request.user,
            )


        except BusinessException as exc:

            return Response(
                {
                    "success": False,
                    "message": str(exc),
                    "data": None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Producto desactivado "
                    "correctamente."
                ),
                "data": None,
            },
            status=status.HTTP_200_OK,
        )