"""Pruebas de desglose de corte con PostgreSQL temporal de Django.

No cambia el calculo de cierre ni requiere nuevas migraciones.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from cajas.models import Caja
from corte_caja.models import MovimientoCaja
from corte_caja.serializers import CorteCajaSerializer
from corte_caja.services import abrir_caja, cerrar_caja
from metodos_pago.models import MetodoPago
from usuarios.models import Usuario
from ventas.models import Venta


class DesgloseMetodosPagoCorteDBTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(
            usuario="cajera_desglose", email="desglose@prueba.invalid",
            password="ClaveTemporal123!", nombre="Cajera", apellido="Prueba", rol=2,
        )
        cls.otro_usuario = Usuario.objects.create_user(
            usuario="cajero_externo", email="externo@prueba.invalid",
            password="ClaveTemporal123!", nombre="Otro", apellido="Cajero", rol=2,
        )
        cls.caja = Caja.objects.create(nombre="Caja para desglose")
        cls.efectivo = MetodoPago.objects.create(nombre="EFECTIVO")
        cls.tarjeta = MetodoPago.objects.create(nombre="TARJETA")
        cls.transferencia = MetodoPago.objects.create(nombre="TRANSFERENCIA")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.usuario)

    def abrir(self):
        return abrir_caja(str(self.caja.id), "1000.00", self.usuario)

    def venta(self, corte, metodo, total, folio, estado="COMPLETADA"):
        return Venta.objects.create(
            folio=folio, corte_caja=corte, usuario=self.usuario,
            metodo_pago=metodo, subtotal=Decimal(total), descuento=Decimal("0.00"),
            iva=Decimal("0.00"), total=Decimal(total), estado=estado,
        )

    def reembolso(self, corte, metodo, monto):
        return MovimientoCaja.objects.create(
            corte_caja=corte, metodo_pago=metodo, tipo="REEMBOLSO",
            monto=Decimal(monto), usuario=self.usuario,
        )

    def valor(self, respuesta, campo):
        return Decimal(str(respuesta[campo]))

    def test_resumen_http_detalla_ventas_y_reembolsos_y_concuerda_con_cierre(self):
        corte = self.abrir()
        self.venta(corte, self.efectivo, "350.00", "DESC-EF-1")
        self.venta(corte, self.tarjeta, "500.00", "DESC-TA-1")
        self.venta(corte, self.transferencia, "200.00", "DESC-TR-1", estado="DEVUELTA")
        self.reembolso(corte, self.efectivo, "50.00")
        self.reembolso(corte, self.tarjeta, "30.00")
        self.reembolso(corte, self.transferencia, "20.00")

        respuesta = self.client.get("/api/caja/corte/activo/", {"caja_id": str(self.caja.id)})
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        data = respuesta.data["data"]
        esperado = {
            "total_ventas_efectivo": "350.00",
            "total_ventas_tarjeta": "500.00",
            "total_ventas_transferencia": "200.00",
            "total_ventas": "1050.00",
            "total_reembolsos_efectivo": "50.00",
            "total_reembolsos_tarjeta": "30.00",
            "total_reembolsos_transferencia": "20.00",
            "total_reembolsos": "100.00",
            "efectivo_esperado_actual": "1300.00",
        }
        for campo, importe in esperado.items():
            with self.subTest(campo=campo):
                self.assertEqual(self.valor(data, campo), Decimal(importe))
        self.assertEqual(data["numero_ventas"], 3)

        resultado = self.client.post("/api/caja/cerrar/", {
            "caja_id": str(self.caja.id), "efectivo_final": "1280.00"
        }, format="json")
        self.assertEqual(resultado.status_code, 200, resultado.data)
        self.assertEqual(self.valor(resultado.data["data"], "efectivo_esperado"), Decimal("1300.00"))
        self.assertEqual(self.valor(resultado.data["data"], "diferencia"), Decimal("-20.00"))

    def test_canceladas_no_entran_en_desglose_ni_efectivo_esperado(self):
        corte = self.abrir()
        self.venta(corte, self.efectivo, "999.00", "DESC-CANCEL-1", estado="CANCELADA")
        self.venta(corte, self.tarjeta, "70.00", "DESC-CANCEL-2")
        datos = self.client.get("/api/caja/corte/activo/", {"caja_id": str(self.caja.id)}).data["data"]
        self.assertEqual(self.valor(datos, "total_ventas_efectivo"), Decimal("0"))
        self.assertEqual(self.valor(datos, "total_ventas_tarjeta"), Decimal("70"))
        self.assertEqual(self.valor(datos, "efectivo_esperado_actual"), Decimal("1000"))
        self.assertEqual(datos["numero_ventas"], 1)

    def test_sin_movimientos_desglose_cero_y_fondo_inicial(self):
        self.abrir()
        datos = self.client.get("/api/caja/corte/activo/", {"caja_id": str(self.caja.id)}).data["data"]
        for campo in (
            "total_ventas_efectivo", "total_ventas_tarjeta", "total_ventas_transferencia",
            "total_reembolsos_efectivo", "total_reembolsos_tarjeta", "total_reembolsos_transferencia",
        ):
            self.assertEqual(self.valor(datos, campo), Decimal("0"), campo)
        self.assertEqual(self.valor(datos, "efectivo_esperado_actual"), Decimal("1000"))

    def test_historial_cerrado_conserva_desglose(self):
        corte = self.abrir()
        self.venta(corte, self.efectivo, "35.00", "DESC-HIST-1")
        self.venta(corte, self.transferencia, "60.00", "DESC-HIST-2")
        cerrar_caja(str(self.caja.id), "1035.00", self.usuario)
        respuesta = self.client.get(f"/api/caja/cajas/{self.caja.id}/cortes/")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        datos = respuesta.data.get("results", respuesta.data.get("data", []))
        self.assertEqual(len(datos), 1)
        self.assertEqual(self.valor(datos[0], "total_ventas_efectivo"), Decimal("35"))
        self.assertEqual(self.valor(datos[0], "total_ventas_transferencia"), Decimal("60"))
        self.assertEqual(self.valor(datos[0], "efectivo_esperado_actual"), Decimal("1035"))

    def test_serializer_directo_y_endpoint_anotado_coinciden(self):
        corte = self.abrir()
        self.venta(corte, self.efectivo, "10.00", "DESC-ANOT-1")
        self.reembolso(corte, self.efectivo, "3.00")
        directo = CorteCajaSerializer(corte).data
        anotado = self.client.get("/api/caja/corte/activo/", {"caja_id": str(self.caja.id)}).data["data"]
        for campo in (
            "total_ventas", "total_ventas_efectivo", "total_ventas_tarjeta",
            "total_ventas_transferencia", "total_reembolsos", "total_reembolsos_efectivo",
            "total_reembolsos_tarjeta", "total_reembolsos_transferencia", "efectivo_esperado_actual",
        ):
            self.assertEqual(self.valor(directo, campo), self.valor(anotado, campo), campo)

    def test_empleado_no_puede_consultar_turno_de_otro(self):
        self.abrir()
        otro = APIClient()
        otro.force_authenticate(user=self.otro_usuario)
        respuesta = otro.get("/api/caja/corte/activo/", {"caja_id": str(self.caja.id)})
        self.assertEqual(respuesta.status_code, 404, respuesta.data)
