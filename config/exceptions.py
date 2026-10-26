
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    Throttled,
    ValidationError,
)


class BusinessException(Exception):
    """
    Excepción para errores de negocio esperados.

    Ejemplos:
    - Stock insuficiente.
    - Caja cerrada.
    - Estado inválido.
    - Plazo vencido.
    """

    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data


def custom_exception_handler(exc, context):
    """
    Manejador global de excepciones del POS.

    Mantiene el formato:
    {
        "success": False,
        "message": "...",
        "data": ...
    }

    Conserva los códigos HTTP originales de DRF.
    """

    # 1. Errores de negocio
    if isinstance(exc, BusinessException):
        return Response(
            {
                "success": False,
                "message": str(exc),
                "data": exc.data,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 2. Manejo original de Django REST Framework
    response = exception_handler(exc, context)

    # No ocultar excepciones inesperadas.
    # Django conserva su manejo de errores 500.
    if response is None:
        return None

    data = None

    # 3. Validaciones de campos
    if isinstance(exc, ValidationError):
        data = response.data
        message = "La solicitud no es válida."

        # Validaciones generales que no pertenecen
        # a un campo específico.
        if isinstance(data, list) and data:
            message = str(data[0])

        elif isinstance(data, dict):
            non_field_errors = data.get("non_field_errors")

            if isinstance(non_field_errors, list) and non_field_errors:
                message = str(non_field_errors[0])
            elif isinstance(non_field_errors, str) and non_field_errors:
                message = non_field_errors

    # 4. Autenticación
    elif isinstance(exc, NotAuthenticated):
        message = "Debes iniciar sesión para realizar esta acción."

    elif isinstance(exc, AuthenticationFailed):
        message = "No fue posible autenticar la solicitud."

    # 5. Permisos
    elif isinstance(exc, PermissionDenied):
        message = "No tienes permisos para realizar esta acción."

    # 6. Demasiadas solicitudes
    elif isinstance(exc, Throttled):
        message = (
            "Has realizado demasiadas solicitudes. "
            "Intenta nuevamente más tarde."
        )

    # 7. Recursos no encontrados
    elif response.status_code == status.HTTP_404_NOT_FOUND:
        original = ""

        if isinstance(response.data, dict):
            original = str(response.data.get("detail", ""))

        if original in (
            "La página solicitada no es válida.",
            "Invalid page.",
        ):
            message = "La página solicitada no es válida."
        else:
            message = "El recurso solicitado no existe."

    # 8. Otras excepciones administradas por DRF
    elif isinstance(response.data, dict):
        detail = response.data.get("detail")

        if detail is not None:
            message = str(detail)
        else:
            message = "La solicitud no es válida."
            data = response.data

    else:
        message = str(response.data)

    # 9. Formato estándar
    response.data = {
        "success": False,
        "message": message,
        "data": data,
    }

    return response
