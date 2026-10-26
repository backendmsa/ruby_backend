"""Pruebas iniciales de corte de caja sin acceso a BD ni operaciones reales.

Ubicación en el proyecto: corte_caja/test_corte_caja_sin_bd.py
Ejecutar desde ruby_backend:
    python manage.py test corte_caja.test_corte_caja_sin_bd -v 2

NOTA: comprueban validaciones y cálculo del resumen; para comprobar el cierre
real faltan pruebas de integración en una base PostgreSQL exclusiva de pruebas.
"""

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from config.exceptions import BusinessException
from corte_caja.serializers import CorteCajaSerializer
from corte_caja.services import validar_efectivo, validar_uuid_caja


class ValidacionesCajaTests(SimpleTestCase):
    def test_efectivo_inicial_cero_es_valido(self):
        self.assertEqual(validar_efectivo("0", "efectivo inicial"), Decimal("0.00"))

    def test_efectivo_inicial_mil_es_valido(self):
        self.assertEqual(validar_efectivo("1000", "efectivo inicial"), Decimal("1000.00"))

    def test_efectivo_negativo_es_rechazado(self):
        with self.assertRaisesRegex(BusinessException, "no puede ser negativo"):
            validar_efectivo("-0.01", "efectivo final")

    def test_efectivo_no_numerico_es_rechazado(self):
        with self.assertRaisesRegex(BusinessException, "no es un valor numérico válido"):
            validar_efectivo("abc", "efectivo inicial")

    def test_efectivo_no_finito_es_rechazado(self):
        with self.assertRaisesRegex(BusinessException, "no es un valor válido"):
            validar_efectivo("NaN", "efectivo final")

    def test_caja_id_obligatorio(self):
        with self.assertRaisesRegex(BusinessException, "obligatorio"):
            validar_uuid_caja(None)

    def test_caja_id_invalido(self):
        with self.assertRaisesRegex(BusinessException, "UUID válido"):
            validar_uuid_caja("id-invalido")


class ResumenCorteCajaTests(SimpleTestCase):
    def setUp(self):
        self.serializer = CorteCajaSerializer()

    def corte_resumido(self, *, inicial, total_ventas, ventas_efectivo, reembolsos, reembolsos_efectivo, numero=3):
        return SimpleNamespace(
            efectivo_inicial=Decimal(inicial),
            _total_ventas=Decimal(total_ventas),
            _numero_ventas=numero,
            _total_reembolsos=Decimal(reembolsos),
            _total_efectivo_ventas=Decimal(ventas_efectivo),
            _total_reembolsos_efectivo=Decimal(reembolsos_efectivo),
        )

    def test_solo_efectivo_aumenta_el_dinero_en_caja(self):
        corte = self.corte_resumido(
            inicial="1000.00", total_ventas="1050.00", ventas_efectivo="350.00",
            reembolsos="50.00", reembolsos_efectivo="50.00",
        )
        self.assertEqual(self.serializer.get_total_ventas(corte), Decimal("1050.00"))
        self.assertEqual(self.serializer.get_numero_ventas(corte), 3)
        self.assertEqual(
            self.serializer.get_efectivo_esperado_actual(corte),
            Decimal("1300.00"),
        )

    def test_reembolso_con_tarjeta_no_reduce_efectivo(self):
        corte = self.corte_resumido(
            inicial="100.00", total_ventas="300.00", ventas_efectivo="80.00",
            reembolsos="20.00", reembolsos_efectivo="0.00",
        )
        self.assertEqual(self.serializer.get_total_reembolsos(corte), Decimal("20.00"))
        self.assertEqual(
            self.serializer.get_efectivo_esperado_actual(corte),
            Decimal("180.00"),
        )

    def test_sin_movimientos_mantiene_fondo_inicial(self):
        corte = self.corte_resumido(
            inicial="250.00", total_ventas="0.00", ventas_efectivo="0.00",
            reembolsos="0.00", reembolsos_efectivo="0.00", numero=0,
        )
        self.assertEqual(
            self.serializer.get_efectivo_esperado_actual(corte), Decimal("250.00")
        )
