"""Pruebas aisladas del cierre real de caja, sin escribir ni leer PostgreSQL.

Usa el cuerpo original de cerrar_caja (sin el decorador transaction.atomic),
y sustituye el ORM y bitacora por mocks. NO es una prueba de integracion.

Ejecutar: python manage.py test corte_caja.test_cierre_servicio_sin_bd -v 2
"""

import uuid
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from cajas.models import Caja
from config.exceptions import BusinessException
from corte_caja.models import CorteCaja
from corte_caja.services import cerrar_caja


class CierreCajaServicioSinBDTests(SimpleTestCase):
    """Comprueba el servicio original con almacenamiento y reloj simulados."""

    def setUp(self):
        # Evita el decorador @transaction.atomic, que abriria conexion a BD.
        self.cerrar_sin_transaccion = getattr(cerrar_caja, "__wrapped__", None)
        self.assertIsNotNone(
            self.cerrar_sin_transaccion,
            "No se encontro cerrar_caja.__wrapped__; no ejecutar la version decorada en SimpleTestCase.",
        )

        self.usuario = SimpleNamespace(
            id=uuid.uuid4(), activo=True, nombre="Usuario", apellido="Pruebas"
        )
        self.caja = SimpleNamespace(
            id=uuid.uuid4(), nombre="Caja pruebas", activa=True,
            estado=Caja.ESTADO_ABIERTA, save=Mock(),
        )
        self.corte = SimpleNamespace(
            id=uuid.uuid4(), caja=self.caja, usuario_id=self.usuario.id,
            efectivo_inicial=Decimal("1000.00"),
            efectivo_final=None, diferencia=None, fecha_fin=None, save=Mock(),
        )

        # Los ORM managers se sustituyen: ninguna consulta puede salir a PostgreSQL.
        self.cajas_lock = self.enterContext(
            patch("corte_caja.services.Caja.objects.select_for_update")
        )
        self.cajas_lock.return_value.get.return_value = self.caja

        self.cortes_lock = self.enterContext(
            patch("corte_caja.services.CorteCaja.objects.select_for_update")
        )
        self.cortes_lock.return_value.get.return_value = self.corte

        self.ventas_filter = self.enterContext(
            patch("corte_caja.services.Venta.objects.filter")
        )
        self.reembolsos_filter = self.enterContext(
            patch("corte_caja.services.MovimientoCaja.objects.filter")
        )
        self.registrar = self.enterContext(
            patch("corte_caja.services.registrar_bitacora")
        )
        self.fecha_cierre = datetime(2026, 10, 25, 12, 0, tzinfo=datetime_timezone.utc)
        self.enterContext(patch("corte_caja.services.timezone.now", return_value=self.fecha_cierre))

        self.ventas_filter.return_value.aggregate.return_value = {"total": Decimal("0.00")}
        self.reembolsos_filter.return_value.aggregate.return_value = {"total": Decimal("0.00")}

    def _cerrar(self, efectivo_final="1000.00", ventas_efectivo="0.00", reembolsos_efectivo="0.00"):
        self.ventas_filter.return_value.aggregate.return_value = {
            "total": Decimal(ventas_efectivo)
        }
        self.reembolsos_filter.return_value.aggregate.return_value = {
            "total": Decimal(reembolsos_efectivo)
        }
        return self.cerrar_sin_transaccion(
            str(self.caja.id), efectivo_final, self.usuario
        )

    def test_ventas_mixtas_y_reembolso_en_efectivo_dan_faltante_20(self):
        corte, esperado, diferencia = self._cerrar(
            efectivo_final="1280.00", ventas_efectivo="350.00", reembolsos_efectivo="50.00"
        )
        self.assertIs(corte, self.corte)
        self.assertEqual(esperado, Decimal("1300.00"))
        self.assertEqual(diferencia, Decimal("-20.00"))
        self.assertEqual(self.corte.efectivo_final, Decimal("1280.00"))
        self.assertEqual(self.corte.diferencia, Decimal("-20.00"))
        self.assertEqual(self.corte.fecha_fin, self.fecha_cierre)
        self.assertEqual(self.caja.estado, Caja.ESTADO_CERRADA)
        self.corte.save.assert_called_once_with(
            update_fields=["efectivo_final", "diferencia", "fecha_fin"]
        )
        self.caja.save.assert_called_once_with(update_fields=["estado"])
        self.registrar.assert_called_once()
        # Garantizar que el filtro excluya otros metodos y ventas canceladas.
        self.ventas_filter.assert_called_once_with(
            corte_caja=self.corte,
            metodo_pago__nombre="EFECTIVO",
            estado__in=["COMPLETADA", "DEVUELTA"],
        )
        self.reembolsos_filter.assert_called_once_with(
            corte_caja=self.corte, metodo_pago__nombre="EFECTIVO", tipo="REEMBOLSO"
        )

    def test_cierre_exacto_no_registra_diferencia(self):
        _, esperado, diferencia = self._cerrar(
            efectivo_final="1350.00", ventas_efectivo="350.00"
        )
        self.assertEqual(esperado, Decimal("1350.00"))
        self.assertEqual(diferencia, Decimal("0.00"))

    def test_sobrante_se_registra_positivo(self):
        _, esperado, diferencia = self._cerrar(
            efectivo_final="1025.50", ventas_efectivo="0.00"
        )
        self.assertEqual(esperado, Decimal("1000.00"))
        self.assertEqual(diferencia, Decimal("25.50"))

    def test_sin_ventas_el_fondo_inicial_se_conserva(self):
        _, esperado, diferencia = self._cerrar(efectivo_final="1000.00")
        self.assertEqual(esperado, Decimal("1000.00"))
        self.assertEqual(diferencia, Decimal("0.00"))

    def test_usuario_diferente_no_puede_cerrar(self):
        self.corte.usuario_id = uuid.uuid4()
        with self.assertRaisesRegex(BusinessException, "Solo puedes cerrar"):
            self._cerrar()
        self.corte.save.assert_not_called()
        self.caja.save.assert_not_called()
        self.registrar.assert_not_called()

    def test_caja_ya_cerrada_no_permite_otro_cierre(self):
        self.caja.estado = Caja.ESTADO_CERRADA
        with self.assertRaisesRegex(BusinessException, "no se encuentra en estado abierta"):
            self._cerrar()
        self.corte.save.assert_not_called()
        self.registrar.assert_not_called()

    def test_no_existe_corte_abierto_no_permite_cierre(self):
        self.cortes_lock.return_value.get.side_effect = CorteCaja.DoesNotExist
        with self.assertRaisesRegex(BusinessException, "No existe un corte abierto"):
            self._cerrar()
        self.corte.save.assert_not_called()
        self.registrar.assert_not_called()

    def test_efectivo_negativo_rechazado_antes_de_consultar_caja(self):
        with self.assertRaisesRegex(BusinessException, "no puede ser negativo"):
            self._cerrar(efectivo_final="-1")
        self.cajas_lock.assert_not_called()
        self.corte.save.assert_not_called()
        self.registrar.assert_not_called()
