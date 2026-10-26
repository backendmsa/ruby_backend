"""Pruebas del contrato de errores de Belleza POS (sin acceso a base de datos).

Ubicación en el proyecto: config/test_mensajes_error.py
Ejecutar desde ruby_backend:
    python manage.py test config.test_mensajes_error -v 2
"""

from django.test import SimpleTestCase
from rest_framework import serializers, status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)

from config.exceptions import BusinessException, custom_exception_handler


class ValidacionEjemploSerializer(serializers.Serializer):
    nombre = serializers.CharField()
    cantidad = serializers.IntegerField(min_value=1)


class MensajesErrorTests(SimpleTestCase):
    def manejar(self, exc):
        response = custom_exception_handler(exc, {})
        self.assertIsNotNone(response)
        self.assertEqual(response.data["success"], False)
        return response

    def test_error_negocio_conserva_mensaje_y_contexto(self):
        exc = BusinessException(
            "Stock insuficiente.",
            data={"stock_actual": 2, "cantidad_solicitada": 5},
        )
        response = self.manejar(exc)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], "Stock insuficiente.")
        self.assertEqual(response.data["data"]["stock_actual"], 2)

    def test_error_de_campo_conserva_su_detalle(self):
        exc = ValidationError({"codigo_barras": ["El código ya existe."]})
        response = self.manejar(exc)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("código", str(response.data["data"]["codigo_barras"][0]))
        self.assertEqual(response.data["message"], "La solicitud no es válida.")

    def test_error_general_de_validacion_muestra_causa(self):
        exc = ValidationError({"non_field_errors": ["Los datos no coinciden."]})
        response = self.manejar(exc)
        self.assertEqual(response.data["message"], "Los datos no coinciden.")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_error_de_validacion_en_lista_muestra_causa(self):
        response = self.manejar(ValidationError(["Cantidad incorrecta."]))
        self.assertEqual(response.data["message"], "Cantidad incorrecta.")

    def test_sesion_no_autenticada(self):
        response = self.manejar(NotAuthenticated())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("iniciar sesión", response.data["message"])

    def test_autenticacion_fallida_no_expone_detalles(self):
        response = self.manejar(AuthenticationFailed("Token is invalid"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["message"], "No fue posible autenticar la solicitud.")
        self.assertNotIn("Token", response.data["message"])

    def test_sin_permisos(self):
        response = self.manejar(PermissionDenied())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("permisos", response.data["message"])

    def test_limite_solicitudes(self):
        response = self.manejar(Throttled(wait=30))
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("demasiadas solicitudes", response.data["message"])
        self.assertEqual(response.get("Retry-After"), "30")

    def test_recurso_inexistente(self):
        response = self.manejar(NotFound())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["message"], "El recurso solicitado no existe.")

    def test_mensaje_de_pagina_invalida(self):
        response = self.manejar(NotFound("Invalid page."))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["message"], "La página solicitada no es válida.")

    def test_campo_obligatorio_traducido_al_espanol(self):
        serializer = ValidacionEjemploSerializer(data={"cantidad": 2})
        self.assertFalse(serializer.is_valid())
        mensaje = str(serializer.errors["nombre"][0]).lower()
        self.assertTrue(
            any(t in mensaje for t in ("obligatorio", "requerido", "necesario")),
            f"El campo obligatorio no parece estar traducido: {mensaje!r}",
        )
