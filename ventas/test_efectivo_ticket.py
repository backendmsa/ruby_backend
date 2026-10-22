"""Pruebas aisladas de importes de efectivo, sin registrar ventas reales."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from config.exceptions import BusinessException
from ventas.services import validar_efectivo_recibido
from tickets.services import generar_ticket
from tickets.serializers import TicketSerializer


class ValidarEfectivoRecibidoTests(SimpleTestCase):
    def test_omision_compatible(self):
        self.assertIsNone(validar_efectivo_recibido(None, Decimal("20.00"), "Efectivo"))

    def test_efectivo_exactamente_total(self):
        self.assertEqual(validar_efectivo_recibido("20.00", Decimal("20.00"), "Efectivo"), Decimal("20.00"))

    def test_efectivo_mayor_total(self):
        self.assertEqual(validar_efectivo_recibido("50", Decimal("20.00"), "Efectivo"), Decimal("50.00"))

    def test_efectivo_insuficiente(self):
        with self.assertRaises(BusinessException):
            validar_efectivo_recibido("19.99", Decimal("20.00"), "Efectivo")

    def test_no_acepta_dato_efectivo_en_tarjeta(self):
        with self.assertRaises(BusinessException):
            validar_efectivo_recibido("50", Decimal("20.00"), "Tarjeta")

    def test_no_acepta_cantidad_con_mas_de_dos_decimales(self):
        with self.assertRaises(BusinessException):
            validar_efectivo_recibido("20.001", Decimal("20.00"), "Efectivo")

    def test_no_acepta_nan(self):
        with self.assertRaises(BusinessException):
            validar_efectivo_recibido("NaN", Decimal("20.00"), "Efectivo")

    def test_no_acepta_negativo(self):
        with self.assertRaises(BusinessException):
            validar_efectivo_recibido("-1", Decimal("20.00"), "Efectivo")


class TicketEfectivoTests(SimpleTestCase):
    def test_ticket_con_efectivo_tiene_cambio(self):
        venta = SimpleNamespace(
            folio="TEST-001", fecha="2026-10-22T08:30:00Z", estado="COMPLETADA",
            metodo_pago=SimpleNamespace(nombre="Efectivo"),
            usuario=SimpleNamespace(nombre="Cajera"),
            detalles=SimpleNamespace(all=lambda: []),
            subtotal=Decimal("185.00"), descuento=Decimal("0.00"),
            iva=Decimal("0.00"), total=Decimal("185.00"),
            efectivo_recibido=Decimal("200.00"),
        )
        empresa = SimpleNamespace(
            nombre="Belleza Pruebas", telefono="", direccion="", rfc="", mensaje_ticket="Gracias",
        )
        with patch("tickets.services.Empresa.objects.first", return_value=empresa):
            data = generar_ticket(venta)
        serializado = TicketSerializer(data).data
        self.assertEqual(serializado["venta"]["efectivo_recibido"], "200.00")
        self.assertEqual(serializado["venta"]["cambio"], "15.00")

    def test_ticket_antiguo_no_inventa_importes(self):
        venta = SimpleNamespace(
            folio="TEST-OLD", fecha="2026-10-22T08:30:00Z", estado="COMPLETADA",
            metodo_pago=SimpleNamespace(nombre="Tarjeta"),
            usuario=SimpleNamespace(nombre="Cajera"),
            detalles=SimpleNamespace(all=lambda: []),
            subtotal=Decimal("185.00"), descuento=Decimal("0.00"),
            iva=Decimal("0.00"), total=Decimal("185.00"),
            efectivo_recibido=None,
        )
        empresa = SimpleNamespace(
            nombre="Belleza Pruebas", telefono="", direccion="", rfc="", mensaje_ticket="Gracias",
        )
        with patch("tickets.services.Empresa.objects.first", return_value=empresa):
            data = generar_ticket(venta)
        serializado = TicketSerializer(data).data
        self.assertIsNone(serializado["venta"]["efectivo_recibido"])
        self.assertIsNone(serializado["venta"]["cambio"])
