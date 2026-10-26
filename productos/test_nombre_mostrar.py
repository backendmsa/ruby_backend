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

    def test_unica_y_registro_duplicado_de_articulo_historico(self):
        categoria = Categoria.objects.create(nombre="CABELLO")
        producto = Producto.objects.create(nombre="Suavizante en spray NBC", categoria=categoria)
        Variante.objects.create(producto=producto, nombre="110 ml", sku="UNICA1234")
        respuesta = self.api.post("/api/productos/registro-completo/", {
            "nombre": "Suavizante en spray NBC - 110 ml",
            "precio_menudeo": "70.00",
        }, format="json")
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertEqual(Variante.objects.count(), 1)

    def test_editar_una_presentacion_historica_muestra_nombre_completo(self):
        categoria = Categoria.objects.create(nombre="CABELLO")
        producto = Producto.objects.create(nombre="Suavizante en spray NBC", categoria=categoria)
        uno = Variante.objects.create(producto=producto, nombre="110 ml", sku="SKU110")
        dos = Variante.objects.create(producto=producto, nombre="220 ml", sku="SKU220")
        r = self.api.patch(f"/api/variantes/{uno.pk}/", {
            "nombre_completo": "Nueva marca suave - 150 ml",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        uno.refresh_from_db()
        dos.refresh_from_db()
        producto.refresh_from_db()
        self.assertEqual(uno.nombre, "110 ml")
        self.assertEqual(uno.nombre_completo, "Nueva marca suave - 150 ml")
        self.assertEqual(dos.nombre, "220 ml")
        self.assertEqual(producto.nombre, "Suavizante en spray NBC")
        listado = self.api.get("/api/productos/articulos/?search=Nueva marca suave")
        self.assertEqual(listado.status_code, 200, listado.data)
        self.assertEqual(listado.data["results"][0]["nombre_mostrar"], "Nueva marca suave - 150 ml")

    def test_edicion_no_permite_duplicado_con_otra_presentacion(self):
        categoria = Categoria.objects.create(nombre="CABELLO")
        producto = Producto.objects.create(nombre="Suavizante en spray NBC", categoria=categoria)
        uno = Variante.objects.create(producto=producto, nombre="110 ml")
        dos = Variante.objects.create(producto=producto, nombre="220 ml")
        r = self.api.patch(f"/api/variantes/{dos.pk}/", {
            "nombre_completo": "SUAVIZANTE EN SPRAY NBC - 110 ML",
        }, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        dos.refresh_from_db()
        self.assertEqual(dos.nombre, "220 ml")
        self.assertIsNone(dos.nombre_completo)

    def test_renombrar_articulo_nuevo_deja_un_solo_nombre(self):
        r = self.api.post("/api/productos/registro-completo/", {
            "nombre": "Mascarilla original", "precio_menudeo": "70.00",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        id_variante = r.data["data"]["variante_id"]
        r = self.api.patch(f"/api/variantes/{id_variante}/", {
            "nombre_completo": "Mascarilla renovada",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        v = Variante.objects.get(pk=id_variante)
        self.assertEqual(v.nombre, "Mascarilla renovada")
        self.assertEqual(v.producto.nombre, "Mascarilla renovada")
        self.assertIsNone(v.nombre_completo)

    def test_rename_no_reasigna_id_producto_ni_variante(self):
        categoria = Categoria.objects.create(nombre="CABELLO")
        producto = Producto.objects.create(nombre="Spray NBC", categoria=categoria)
        uno = Variante.objects.create(producto=producto, nombre="110 ml")
        dos = Variante.objects.create(producto=producto, nombre="220 ml")
        antes = (uno.pk, uno.producto_id)
        r = self.api.patch(f"/api/variantes/{uno.pk}/", {
            "nombre_completo": "Spray distinto 110 ml",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        uno.refresh_from_db()
        self.assertEqual((uno.pk, uno.producto_id), antes)
        dos.refresh_from_db()
        self.assertEqual(dos.nombre, "220 ml")
