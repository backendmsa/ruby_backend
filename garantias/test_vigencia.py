"""Pruebas unitarias sin acceso a datos de producción."""
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from config.exceptions import BusinessException
from detalle_venta.garantia import meses_de_garantia, fecha_vencimiento_de_garantia
from garantias.services import _validar_vigencia


class VigenciaGarantiaTests(SimpleTestCase):
    def detalle(self, meses_venta, meses_actual, fecha):
        return SimpleNamespace(
            garantia_meses=meses_venta,
            variante=SimpleNamespace(garantia_meses=meses_actual),
            venta=SimpleNamespace(fecha=fecha),
        )

    def test_usa_plazo_original_aunque_variante_cambie(self):
        detalle = self.detalle(12, 1, datetime(2026, 1, 31, 10, tzinfo=dt_timezone.utc))
        self.assertEqual(meses_de_garantia(detalle), 12)
        self.assertEqual(fecha_vencimiento_de_garantia(detalle).date().isoformat(), "2027-01-31")

    def test_sin_garantia_nueva_no_recibe_cobertura_retroactiva(self):
        detalle = self.detalle(0, 12, datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
        self.assertIsNone(fecha_vencimiento_de_garantia(detalle))
        with self.assertRaisesRegex(BusinessException, "no tiene garantía"):
            _validar_vigencia(detalle)

    def test_venta_antigua_sin_captura_conserva_comportamiento(self):
        detalle = self.detalle(None, 3, datetime(2026, 1, 31, tzinfo=dt_timezone.utc))
        self.assertEqual(meses_de_garantia(detalle), 3)
        self.assertEqual(fecha_vencimiento_de_garantia(detalle).date().isoformat(), "2026-04-30")

    def test_vencida_se_rechaza(self):
        detalle = self.detalle(2, 12, datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
        with patch("garantias.services.timezone.now", return_value=datetime(2026, 3, 2, tzinfo=dt_timezone.utc)):
            with self.assertRaisesRegex(BusinessException, "venció"):
                _validar_vigencia(detalle)

    def test_vigente_se_acepta(self):
        detalle = self.detalle(6, 1, datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
        with patch("garantias.services.timezone.now", return_value=datetime(2026, 2, 1, tzinfo=dt_timezone.utc)):
            self.assertIsNone(_validar_vigencia(detalle))
