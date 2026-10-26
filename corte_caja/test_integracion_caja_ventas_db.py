r"""Pruebas PostgreSQL de integración para caja, ventas y corte de Belleza POS.

Ejecutar SOLO en el entorno LOCAL preparado para pruebas:
    .\.venv\Scripts\python.exe manage.py test corte_caja.test_integracion_caja_ventas_db -v 2

Django crea una BD de pruebas separada (test_<DB_NAME>) y la destruye al acabar.
NO usa ni modifica ventas/cajas existentes de ruby_pos_clean.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from cajas.models import Caja
from categorias.models import Categoria
from config.exceptions import BusinessException
from corte_caja.models import CorteCaja, MovimientoCaja
from corte_caja.serializers import CorteCajaSerializer
from corte_caja.services import abrir_caja, cerrar_caja
from empresa.models import Empresa
from inventario.models import MovimientoInventario
from metodos_pago.models import MetodoPago
from productos.models import Producto
from usuarios.models import Usuario
from variantes.models import Variante
from ventas.models import Venta
from ventas.services import cancelar_venta, crear_venta


class IntegracionCajaVentasDBTests(TestCase):
    """Pruebas con ORM real y transacciones en la base de pruebas de Django."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(
            usuario="testcaja_empleado",
            email="testcaja_empleado@example.invalid",
            password="ClaveDePruebas123!",
            nombre="Cajera",
            apellido="Pruebas",
            rol=2,
        )
        cls.otro_usuario = Usuario.objects.create_user(
            usuario="testcaja_otro",
            email="testcaja_otro@example.invalid",
            password="ClaveDePruebas123!",
            nombre="Otro",
            apellido="Empleado",
            rol=2,
        )
        cls.caja = Caja.objects.create(nombre="Caja exclusiva de prueba")
        cls.efectivo = MetodoPago.objects.create(nombre="EFECTIVO")
        cls.tarjeta = MetodoPago.objects.create(nombre="TARJETA")
        cls.transferencia = MetodoPago.objects.create(nombre="TRANSFERENCIA")
        Empresa.objects.create(
            nombre="Empresa de pruebas aisladas",
            direccion="Dirección de prueba",
            mensaje_ticket="Ticket de prueba",
            iva=Decimal("0.00"),
            dias_devolucion=30,
        )
        categoria = Categoria.objects.create(nombre="Pruebas de integración")
        producto = Producto.objects.create(
            categoria=categoria,
            nombre="Producto para integración de caja",
        )
        cls.articulo_350 = Variante.objects.create(
            producto=producto, nombre="Artículo 350", codigo_barras="TESTCAJA350",
            precio_menudeo=Decimal("350.00"), stock=20,
        )
        cls.articulo_500 = Variante.objects.create(
            producto=producto, nombre="Artículo 500", codigo_barras="TESTCAJA500",
            precio_menudeo=Decimal("500.00"), stock=20,
        )
        cls.articulo_200 = Variante.objects.create(
            producto=producto, nombre="Artículo 200", codigo_barras="TESTCAJA200",
            precio_menudeo=Decimal("200.00"), stock=20,
        )

    def _abrir(self, inicial="1000.00"):
        return abrir_caja(str(self.caja.pk), inicial, self.usuario)

    def _vender(self, articulo, metodo, efectivo_recibido=None, cantidad=1):
        data = {
            "caja_id": str(self.caja.pk),
            "metodo_pago_id": str(metodo.pk),
            "productos": [{"variante_id": str(articulo.pk), "cantidad": cantidad}],
            "descuento": "0.00",
        }
        if efectivo_recibido is not None:
            data["efectivo_recibido"] = efectivo_recibido
        return crear_venta(data, self.usuario)

    def test_01_ventas_mixtas_reembolsos_y_faltante_20(self):
        """Tres ventas reales + dos movimientos de reembolso, cierre persistido."""
        corte = self._abrir()
        v1 = self._vender(self.articulo_350, self.efectivo, "400.00")
        v2 = self._vender(self.articulo_500, self.tarjeta)
        v3 = self._vender(self.articulo_200, self.transferencia)
        self.assertEqual([v1.total, v2.total, v3.total], [
            Decimal("350.00"), Decimal("500.00"), Decimal("200.00")
        ])
        # Movimientos reales de modelo, aunque la aprobación de devolución
        # queda para otra prueba de integración independiente.
        MovimientoCaja.objects.create(
            corte_caja=corte, metodo_pago=self.efectivo, tipo="REEMBOLSO",
            monto=Decimal("50.00"), usuario=self.usuario,
        )
        MovimientoCaja.objects.create(
            corte_caja=corte, metodo_pago=self.tarjeta, tipo="REEMBOLSO",
            monto=Decimal("30.00"), usuario=self.usuario,
        )
        resumen_antes = CorteCajaSerializer(corte).data
        self.assertEqual(Decimal(str(resumen_antes["total_ventas"])), Decimal("1050.00"))
        self.assertEqual(Decimal(str(resumen_antes["total_reembolsos"])), Decimal("80.00"))
        self.assertEqual(Decimal(str(resumen_antes["efectivo_esperado_actual"])), Decimal("1300.00"))
        _, esperado, diferencia = cerrar_caja(str(self.caja.pk), "1280.00", self.usuario)
        self.assertEqual(esperado, Decimal("1300.00"))
        self.assertEqual(diferencia, Decimal("-20.00"))
        corte.refresh_from_db()
        self.caja.refresh_from_db()
        self.assertEqual(corte.efectivo_final, Decimal("1280.00"))
        self.assertEqual(corte.diferencia, Decimal("-20.00"))
        self.assertIsNotNone(corte.fecha_fin)
        self.assertEqual(self.caja.estado, Caja.ESTADO_CERRADA)
        self.assertEqual(Venta.objects.filter(corte_caja=corte).count(), 3)
        for variante in (self.articulo_350, self.articulo_500, self.articulo_200):
            variante.refresh_from_db()
            self.assertEqual(variante.stock, 19)
        self.assertEqual(MovimientoInventario.objects.filter(tipo="SALIDA").count(), 3)

    def test_02_efectivo_recibido_y_cambio_no_inflan_caja(self):
        self._abrir()
        venta = self._vender(self.articulo_350, self.efectivo, "500.00")
        self.assertEqual(venta.efectivo_recibido, Decimal("500.00"))
        self.assertEqual(venta.total, Decimal("350.00"))
        _, esperado, diferencia = cerrar_caja(str(self.caja.pk), "1350", self.usuario)
        self.assertEqual(esperado, Decimal("1350.00"))
        self.assertEqual(diferencia, Decimal("0.00"))

    def test_03_cancelacion_no_cuenta_y_restaura_inventario(self):
        corte = self._abrir()
        venta = self._vender(self.articulo_350, self.efectivo, "350.00")
        self._vender(self.articulo_500, self.tarjeta)
        self.articulo_350.refresh_from_db()
        self.assertEqual(self.articulo_350.stock, 19)
        cancelar_venta(str(venta.pk), self.usuario)
        venta.refresh_from_db()
        self.articulo_350.refresh_from_db()
        self.assertEqual(venta.estado, "CANCELADA")
        self.assertEqual(self.articulo_350.stock, 20)
        self.assertEqual(MovimientoInventario.objects.filter(
            variante=self.articulo_350, tipo="ENTRADA"
        ).count(), 1)
        resumen = CorteCajaSerializer(corte).data
        self.assertEqual(Decimal(str(resumen["total_ventas"])), Decimal("500.00"))
        self.assertEqual(int(resumen["numero_ventas"]), 1)
        _, esperado, diferencia = cerrar_caja(str(self.caja.pk), "1000", self.usuario)
        self.assertEqual(esperado, Decimal("1000.00"))
        self.assertEqual(diferencia, Decimal("0.00"))

    def test_04_venta_con_caja_cerrada_no_crea_nada(self):
        with self.assertRaisesMessage(BusinessException, "La caja está cerrada."):
            self._vender(self.articulo_350, self.efectivo, "350.00")
        self.assertEqual(Venta.objects.count(), 0)
        self.assertEqual(MovimientoInventario.objects.count(), 0)

    def test_05_stock_insuficiente_hace_rollback_completo(self):
        self._abrir()
        with self.assertRaisesMessage(BusinessException, "Stock insuficiente."):
            self._vender(self.articulo_350, self.efectivo, "99999.00", cantidad=100)
        self.articulo_350.refresh_from_db()
        self.assertEqual(self.articulo_350.stock, 20)
        self.assertEqual(Venta.objects.count(), 0)
        self.assertEqual(MovimientoInventario.objects.count(), 0)

    def test_06_efectivo_insuficiente_revierte_venta_y_stock(self):
        self._abrir()
        with self.assertRaisesMessage(BusinessException, "El efectivo recibido es menor"):
            self._vender(self.articulo_350, self.efectivo, "100.00")
        self.articulo_350.refresh_from_db()
        self.assertEqual(self.articulo_350.stock, 20)
        self.assertEqual(Venta.objects.count(), 0)
        self.assertEqual(MovimientoInventario.objects.count(), 0)

    def test_07_otro_usuario_no_puede_cerrar(self):
        corte = self._abrir()
        with self.assertRaisesMessage(BusinessException, "Solo puedes cerrar la caja"):
            cerrar_caja(str(self.caja.pk), "1000", self.otro_usuario)
        corte.refresh_from_db()
        self.assertIsNone(corte.fecha_fin)
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, Caja.ESTADO_ABIERTA)
        _, esperado, diferencia = cerrar_caja(str(self.caja.pk), "1000", self.usuario)
        self.assertEqual((esperado, diferencia), (Decimal("1000"), Decimal("0.00")))

    def test_08_no_permite_doble_apertura_ni_doble_cierre(self):
        self._abrir()
        with self.assertRaisesMessage(BusinessException, "Ya existe un corte abierto"):
            self._abrir()
        self.assertEqual(CorteCaja.objects.count(), 1)
        cerrar_caja(str(self.caja.pk), "1000", self.usuario)
        with self.assertRaises(BusinessException):
            cerrar_caja(str(self.caja.pk), "1000", self.usuario)
        self.assertEqual(CorteCaja.objects.count(), 1)

    def test_09_turnos_consecutivos_no_mezclan_ventas(self):
        primer_corte = self._abrir("1000")
        self._vender(self.articulo_350, self.efectivo, "350")
        cerrar_caja(str(self.caja.pk), "1350", self.usuario)
        segundo_corte = self._abrir("250")
        self.assertNotEqual(primer_corte.pk, segundo_corte.pk)
        _, esperado, diferencia = cerrar_caja(str(self.caja.pk), "250", self.usuario)
        self.assertEqual(esperado, Decimal("250.00"))
        self.assertEqual(diferencia, Decimal("0.00"))
        self.assertEqual(Venta.objects.filter(corte_caja=primer_corte).count(), 1)
        self.assertEqual(Venta.objects.filter(corte_caja=segundo_corte).count(), 0)

    def test_10_api_apertura_venta_consulta_y_cierre(self):
        """Prueba endpoint HTTP completo con autenticación simulada, ORM real."""
        client = APIClient()
        client.force_authenticate(user=self.usuario)
        apertura = client.post("/api/caja/abrir/", {
            "caja_id": str(self.caja.pk), "efectivo_inicial": "1000.00"
        }, format="json")
        self.assertEqual(apertura.status_code, 201, apertura.data)
        venta = client.post("/api/ventas/", {
            "caja_id": str(self.caja.pk),
            "metodo_pago_id": str(self.efectivo.pk),
            "productos": [{"variante_id": str(self.articulo_350.pk), "cantidad": 1}],
            "descuento": "0.00",
            "efectivo_recibido": "400.00",
        }, format="json")
        self.assertEqual(venta.status_code, 201, venta.data)
        consulta = client.get("/api/caja/corte/activo/", {
            "caja_id": str(self.caja.pk)
        })
        self.assertEqual(consulta.status_code, 200, consulta.data)
        self.assertEqual(Decimal(str(consulta.data["data"]["efectivo_esperado_actual"])),
                         Decimal("1350.00"))
        cierre = client.post("/api/caja/cerrar/", {
            "caja_id": str(self.caja.pk), "efectivo_final": "1340.00"
        }, format="json")
        self.assertEqual(cierre.status_code, 200, cierre.data)
        self.assertEqual(Decimal(str(cierre.data["data"]["diferencia"])),
                         Decimal("-10.00"))
        self.assertEqual(Decimal(str(cierre.data["data"]["efectivo_esperado"])),
                         Decimal("1350.00"))
