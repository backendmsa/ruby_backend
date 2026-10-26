"""Pruebas aisladas: Django crea una BD de TEST, nunca la base productiva."""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from categorias.models import Categoria
from inventario.models import MovimientoInventario
from productos.models import Producto
from usuarios.models import Usuario
from variantes.models import Variante


class RegistroArticulosSimpleTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            usuario="usuario_prueba_articulo", email="articulo@pruebas.example",
            password="ClaveSoloParaPruebas#1", nombre="Usuario", apellido="Prueba", rol=1,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.usuario)
        self.url = "/api/productos/registro-completo/"

    def alta(self, **cambios):
        data = {"nombre": "Mascarilla de prueba", "precio_menudeo": "70.00"}
        data.update(cambios)
        return self.api.post(self.url, data, format="json")

    def test_minimo_sin_categoria_sku_ni_existencia(self):
        response = self.alta()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Producto.objects.count(), 1)
        variante = Variante.objects.get()
        self.assertEqual(variante.nombre, "Mascarilla de prueba")
        self.assertEqual(variante.producto.nombre, "Mascarilla de prueba")
        self.assertEqual(variante.producto.categoria.nombre, "SIN CLASIFICAR")
        self.assertIsNone(variante.sku)
        self.assertIsNone(variante.codigo_barras)
        self.assertEqual(variante.costo, Decimal("0.00"))
        self.assertEqual(variante.precio_mayoreo, Decimal("0.00"))
        self.assertEqual(variante.stock, 0)
        self.assertEqual(MovimientoInventario.objects.count(), 0)
        self.assertEqual(response.data["data"]["nombre"], variante.nombre)
        self.assertNotIn("producto_nombre", response.data["data"])

    def test_precio_de_venta_y_nombre_son_obligatorios(self):
        casos = [
            {"precio_menudeo": None}, {"precio_menudeo": "0"},
            {"precio_menudeo": "-1"}, {"nombre": ""},
            {"nombre": "   "}, {"nombre": None},
        ]
        for campos in casos:
            with self.subTest(campos=campos):
                response = self.alta(**campos)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Producto.objects.count(), 0)
        self.assertEqual(Variante.objects.count(), 0)

    def test_stock_inicial_crea_movimiento_real(self):
        response = self.alta(stock=14, stock_minimo=2)
        self.assertEqual(response.status_code, 201, response.data)
        variante = Variante.objects.get()
        self.assertEqual((variante.stock, variante.stock_minimo), (14, 2))
        movimiento = MovimientoInventario.objects.get(variante=variante)
        self.assertEqual(
            (movimiento.tipo, movimiento.stock_anterior, movimiento.cantidad, movimiento.stock_nuevo),
            ("ENTRADA", 0, 14, 14),
        )

    def test_campos_nulos_y_vacios_admitidos(self):
        response = self.alta(categoria="", sku="", codigo_barras="",
                             costo=None, precio_mayoreo=None, stock=None, stock_minimo=None)
        self.assertEqual(response.status_code, 201, response.data)
        variante = Variante.objects.get()
        self.assertIsNone(variante.sku)
        self.assertIsNone(variante.codigo_barras)
        self.assertEqual(variante.stock, 0)
        self.assertEqual(variante.stock_minimo, 0)
        self.assertEqual(variante.costo, Decimal("0.00"))

    def test_no_permite_dos_articulos_con_el_mismo_nombre_visible(self):
        self.assertEqual(self.alta().status_code, 201)
        response = self.alta(nombre="  MASCARILLA    de prueba ")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("Ya existe un artículo", response.data["message"])
        self.assertEqual(Variante.objects.count(), 1)

    def test_duplicado_con_categoria_diferente_se_rechaza(self):
        self.assertEqual(self.alta().status_code, 201)
        nueva_categoria = Categoria.objects.create(nombre="OTRA CATEGORIA")
        respuesta = self.alta(categoria=str(nueva_categoria.pk))
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertEqual(Variante.objects.count(), 1)

    def test_duplicado_inactivo_tambien_se_rechaza(self):
        self.assertEqual(self.alta().status_code, 201)
        Variante.objects.update(activo=False)
        respuesta = self.alta()
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertEqual(Variante.objects.count(), 1)

    def test_error_de_variante_revierte_todo_incluso_categoria(self):
        response = self.alta(codigo_barras="INVALIDO")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Producto.objects.count(), 0)
        self.assertEqual(Variante.objects.count(), 0)
        self.assertEqual(Categoria.objects.count(), 0)

    def test_reutiliza_categoria_existente_sin_modificarla(self):
        categoria = Categoria.objects.create(nombre="ACEITES")
        response = self.alta(categoria=str(categoria.pk))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Categoria.objects.count(), 1)
        self.assertEqual(Producto.objects.get().categoria_id, categoria.pk)

    def test_no_acepta_categoria_sin_clasificar_inactiva(self):
        Categoria.objects.create(nombre="SIN CLASIFICAR", activo=False)
        response = self.alta()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Producto.objects.count(), 0)

    def test_lista_variante_nombre_sin_nombre_de_producto(self):
        categoria = Categoria.objects.create(nombre="CABELLO")
        producto = Producto.objects.create(nombre="Shampoo", categoria=categoria)
        Variante.objects.create(producto=producto, nombre="250 ml", sku="PRUEBA250")
        Variante.objects.create(producto=producto, nombre="500 ml", sku="PRUEBA500")
        response = self.api.get("/api/productos/articulos/?page_size=10")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        nombres = {item["nombre"] for item in response.data["results"]}
        self.assertEqual(nombres, {"250 ml", "500 ml"})
        self.assertTrue(all("producto_nombre" not in item for item in response.data["results"]))
        self.assertEqual(Producto.objects.count(), 1)

    def test_no_modifica_productos_historicos(self):
        categoria = Categoria.objects.create(nombre="CABELLO")
        producto = Producto.objects.create(nombre="Shampoo", categoria=categoria)
        uno = Variante.objects.create(producto=producto, nombre="250 ml", sku="PRUEBA250")
        dos = Variante.objects.create(producto=producto, nombre="500 ml", sku="PRUEBA500")
        self.assertEqual(self.alta(nombre="Nuevo aceite").status_code, 201)
        uno.refresh_from_db()
        dos.refresh_from_db()
        producto.refresh_from_db()
        self.assertEqual(producto.nombre, "Shampoo")
        self.assertEqual({uno.nombre, dos.nombre}, {"250 ml", "500 ml"})
        self.assertEqual(uno.producto_id, dos.producto_id)
        self.assertEqual(Producto.objects.count(), 2)

    def test_editar_variante_historica_no_renombra_hermanas(self):
        categoria = Categoria.objects.create(nombre="CABELLO")
        producto = Producto.objects.create(nombre="Shampoo", categoria=categoria)
        primera = Variante.objects.create(producto=producto, nombre="250 ml", sku="HIST250")
        segunda = Variante.objects.create(producto=producto, nombre="500 ml", sku="HIST500")
        response = self.api.patch(
            f"/api/variantes/{primera.pk}/",
            {"nombre": "250 ml NUEVO", "precio_menudeo": "85.00"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        primera.refresh_from_db()
        segunda.refresh_from_db()
        producto.refresh_from_db()
        self.assertEqual(primera.nombre, "250 ml NUEVO")
        self.assertEqual(primera.precio_menudeo, Decimal("85.00"))
        self.assertEqual(segunda.nombre, "500 ml")
        self.assertEqual(producto.nombre, "Shampoo")
