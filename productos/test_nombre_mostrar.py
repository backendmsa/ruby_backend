"""Pruebas para nombre visible y búsqueda por producto padre (base de datos de TEST)."""
from django.test import TestCase
from rest_framework.test import APIClient

from categorias.models import Categoria
from productos.models import Producto
from usuarios.models import Usuario
from variantes.models import Variante


class NombreMostrarArticulosTests(TestCase):
    def setUp(self):
        usuario = Usuario.objects.create_user(
            usuario="prueba_nombre_mostrar", email="nombre-mostrar@pruebas.example",
            password="SoloPruebas#1", nombre="Prueba", apellido="Nombre", rol=1,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=usuario)

    def test_busqueda_producto_padre_y_nombre_completo(self):
        categoria = Categoria.objects.create(nombre="HERRAMIENTAS_ACCESORIOS")
        producto = Producto.objects.create(nombre="Bolsa de Carrete", categoria=categoria)
        variante = Variante.objects.create(producto=producto, nombre="#1", sku="PRUEBA7631")

        for busqueda in ("Bolsa de Carrete", "Bolsa de Carrete - #1"):
            with self.subTest(busqueda=busqueda):
                response = self.api.get("/api/productos/articulos/", {"search": busqueda})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["count"], 1)
                item = response.data["results"][0]
                self.assertEqual(item["variante_id"], str(variante.pk))
                self.assertEqual(item["nombre"], "#1")
                self.assertEqual(item["nombre_mostrar"], "Bolsa de Carrete - #1")

        producto.refresh_from_db()
        variante.refresh_from_db()
        self.assertEqual(producto.nombre, "Bolsa de Carrete")
        self.assertEqual(variante.nombre, "#1")

    def test_unica_y_nombres_nuevos_repetidos(self):
        categoria = Categoria.objects.create(nombre="BELLEZA")
        producto = Producto.objects.create(nombre="Mascarilla Percapelli", categoria=categoria)
        Variante.objects.create(producto=producto, nombre="Única", sku="UNICA1234")
        response = self.api.get("/api/productos/articulos/", {"search": "Mascarilla Percapelli"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"][0]["nombre_mostrar"], "Mascarilla Percapelli")

        datos = {"nombre": "Mascarilla nueva", "precio_menudeo": "70.00"}
        for _ in range(2):
            response = self.api.post("/api/productos/registro-completo/", datos, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["data"]["nombre_mostrar"], datos["nombre"])
        response = self.api.get("/api/productos/articulos/", {"search": datos["nombre"]})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual({r["nombre_mostrar"] for r in response.data["results"]}, {datos["nombre"]})
