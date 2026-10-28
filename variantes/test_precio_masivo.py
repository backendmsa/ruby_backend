"""Pruebas aisladas: no afectan la base de datos de producción."""
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient

from categorias.models import Categoria
from productos.models import Producto
from usuarios.models import Usuario
from variantes.models import Variante


class PrecioMasivoTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            usuario="test_masivo_precios", email="masivos@pruebas.example",
            password="Pruebas#12345", nombre="Prueba", apellido="Precio", rol=1,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.usuario)
        self.categoria = Categoria.objects.create(nombre="MAQUILLAJE TEST MASIVO")
        self.producto = Producto.objects.create(nombre="LABIAL TEST MASIVO", categoria=self.categoria)
        self.rosa = Variante.objects.create(
            producto=self.producto, nombre="ROSA", precio_menudeo="125.00", stock=5,
            costo="50.00", sku="TEST-MASIVO-ROSA",
        )
        self.azul = Variante.objects.create(
            producto=self.producto, nombre="AZUL", precio_menudeo="25.00", stock=7,
            costo="11.00", sku="TEST-MASIVO-AZUL", activo=False,
        )
        self.otro_producto = Producto.objects.create(nombre="LABIAL SUELTO TEST", categoria=self.categoria)
        self.rojo = Variante.objects.create(
            producto=self.otro_producto, nombre="ROJO", precio_menudeo="72.00", stock=9,
            costo="15.00", sku="TEST-MASIVO-ROJO",
        )
        self.url = "/api/variantes/precio-masivo/"

    def test_vista_previa_incluye_inactivos_del_mismo_producto(self):
        r = self.api.get(self.url, {"producto_id": str(self.producto.pk)})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual({v["id"] for v in r.data["data"]}, {str(self.rosa.pk), str(self.azul.pk)})

    def test_actualiza_solo_precios_seleccionados_sin_tocar_stock_costo_ni_sku(self):
        r = self.api.post(self.url, {
            "ids": [str(self.rosa.pk), str(self.azul.pk), str(self.rojo.pk)],
            "precio_menudeo": "10.00", "confirmado": True,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["data"]["actualizadas"], 3)
        for variante in (self.rosa, self.azul, self.rojo):
            variante.refresh_from_db()
            self.assertEqual(variante.precio_menudeo, Decimal("10.00"))
        self.assertEqual((self.rosa.stock, self.azul.stock, self.rojo.stock), (5, 7, 9))
        self.assertEqual(self.rosa.costo, Decimal("50.00"))
        self.assertEqual(self.rosa.sku, "TEST-MASIVO-ROSA")
        self.assertFalse(self.azul.activo)

    def test_grupo_no_cambia_articulos_de_otro_producto(self):
        r = self.api.post(self.url, {
            "ids": [str(self.rosa.pk), str(self.azul.pk)],
            "precio_menudeo": "10.00", "confirmado": True,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.rojo.refresh_from_db()
        self.assertEqual(self.rojo.precio_menudeo, Decimal("72.00"))

    def test_no_confirma_no_cambia_nada(self):
        r = self.api.post(self.url, {
            "ids": [str(self.rosa.pk)], "precio_menudeo": "10.00", "confirmado": False,
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.rosa.refresh_from_db()
        self.assertEqual(self.rosa.precio_menudeo, Decimal("125.00"))

    def test_si_una_variante_no_existe_no_modifica_ninguna(self):
        r = self.api.post(self.url, {
            "ids": [str(self.rosa.pk), "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
            "precio_menudeo": "10.00", "confirmado": True,
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.rosa.refresh_from_db()
        self.assertEqual(self.rosa.precio_menudeo, Decimal("125.00"))

    def test_precio_invalido_y_repetidos_rechazados(self):
        for data in (
            {"ids": [str(self.rosa.pk)], "precio_menudeo": "0.00", "confirmado": True},
            {"ids": [str(self.rosa.pk), str(self.rosa.pk)], "precio_menudeo": "10.00", "confirmado": True},
        ):
            with self.subTest(data=data):
                r = self.api.post(self.url, data, format="json")
                self.assertEqual(r.status_code, 400)

    def test_usuario_sin_autenticacion_rechazado(self):
        self.api.force_authenticate(user=None)
        r = self.api.post(self.url, {
            "ids": [str(self.rosa.pk)], "precio_menudeo": "10.00", "confirmado": True,
        }, format="json")
        self.assertIn(r.status_code, (401, 403))
