"""Pruebas locales: modificación por variante y advertencias que NO bloquean."""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from categorias.models import Categoria
from productos.models import Producto
from usuarios.models import Usuario
from variantes.models import Variante


class EdicionPreciosFlexiblesTests(TestCase):
    def setUp(self):
        user = Usuario.objects.create_user(
            usuario="test_edicion_flexible", email="flexible@pruebas.example",
            password="SoloPruebas#25", nombre="Prueba", apellido="Edición", rol=1,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=user)
        self.categoria = Categoria.objects.create(nombre="CABELLO")

    def nuevo(self, **campos):
        data = {"nombre": "Prueba flexible", "precio_menudeo": "85.00"}
        data.update(campos)
        respuesta = self.api.post("/api/productos/registro-completo/", data, format="json")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return Variante.objects.get(pk=respuesta.data["data"]["variante_id"])

    def patch(self, variante, **datos):
        return self.api.patch(f"/api/variantes/{variante.pk}/", datos, format="json")

    def test_alta_bajo_costo_guarda_y_advierte(self):
        variante = self.nuevo(costo="100.00", precio_menudeo="90.00", precio_mayoreo="80.00")
        self.assertEqual(variante.precio_menudeo, Decimal("90"))
        self.assertEqual(variante.precio_mayoreo, Decimal("80"))
        listado = self.api.get("/api/productos/articulos/", {"search": "Prueba flexible"})
        self.assertEqual(listado.status_code, 200, listado.data)
        avisos = listado.data["results"][0]["advertencias_precios"]
        self.assertEqual({aviso["campo"] for aviso in avisos}, {"precio_menudeo", "precio_mayoreo"})

    def test_edicion_bajo_costo_es_permitida_y_advierte(self):
        variante = self.nuevo(costo="100.00", precio_menudeo="120.00")
        response = self.patch(variante, precio_menudeo="90.00", precio_mayoreo="80.00")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]["advertencias_precios"]), 2)
        variante.refresh_from_db()
        self.assertEqual((variante.precio_menudeo, variante.precio_mayoreo), (90, 80))

    def test_mayoreo_cero_no_muestra_advertencia(self):
        variante = self.nuevo(costo="100.00", precio_menudeo="120.00", precio_mayoreo="90.00")
        r = self.patch(variante, precio_mayoreo="0.00")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["data"]["advertencias_precios"], [])

    def test_precio_venta_cero_y_negativos_se_rechazan(self):
        variante = self.nuevo()
        for cambio in (
            {"precio_menudeo": "0.00"},
            {"precio_menudeo": "-1.00"},
            {"costo": "-1.00"},
            {"precio_mayoreo": "-1.00"},
        ):
            with self.subTest(cambio=cambio):
                r = self.patch(variante, **cambio)
                self.assertEqual(r.status_code, 400, r.data)

    def test_edicion_en_cero_costo_y_mayoreo_opcionales(self):
        variante = self.nuevo(costo="200.00", precio_menudeo="210.00", precio_mayoreo="205.00")
        r = self.patch(variante, costo=None, precio_mayoreo="")
        self.assertEqual(r.status_code, 200, r.data)
        variante.refresh_from_db()
        self.assertEqual(variante.costo, 0)
        self.assertEqual(variante.precio_mayoreo, 0)

    def test_cambiar_categoria_solo_si_no_comparte_producto(self):
        variante = self.nuevo()
        categoria2 = Categoria.objects.create(nombre="ACEITES")
        r = self.patch(variante, categoria=str(categoria2.pk))
        self.assertEqual(r.status_code, 200, r.data)
        variante.refresh_from_db()
        self.assertEqual(variante.producto.categoria_id, categoria2.pk)
        r = self.patch(variante, categoria=None)
        self.assertEqual(r.status_code, 200, r.data)
        variante.refresh_from_db()
        self.assertEqual(variante.producto.categoria.nombre, "SIN CLASIFICAR")

    def test_categoria_compartida_bloqueada_y_precio_individual(self):
        producto = Producto.objects.create(nombre="Bolsa de Carrete", categoria=self.categoria)
        uno = Variante.objects.create(producto=producto, nombre="#1", sku="B7631", costo=50, precio_menudeo=65)
        dos = Variante.objects.create(producto=producto, nombre="#2", sku="B7632", costo=50, precio_menudeo=65)
        categoria2 = Categoria.objects.create(nombre="OTRA")
        r = self.patch(uno, categoria=str(categoria2.pk), precio_menudeo="75.00")
        self.assertEqual(r.status_code, 400, r.data)
        uno.refresh_from_db()
        dos.refresh_from_db()
        self.assertEqual(uno.precio_menudeo, 65)
        self.assertEqual(dos.precio_menudeo, 65)
        self.assertEqual(producto.categoria_id, self.categoria.pk)
        r = self.patch(uno, nombre="#1 Azul", precio_menudeo="75.00")
        self.assertEqual(r.status_code, 200, r.data)
        uno.refresh_from_db()
        dos.refresh_from_db()
        self.assertEqual((uno.nombre, uno.precio_menudeo), ("#1 Azul", 75))
        self.assertEqual((dos.nombre, dos.precio_menudeo), ("#2", 65))
        producto.refresh_from_db()
        self.assertEqual(producto.nombre, "Bolsa de Carrete")

    def test_renombre_nuevo_no_muestra_nombre_anterior(self):
        variante = self.nuevo(nombre="Mascarilla Nueva")
        r = self.patch(variante, nombre="Mascarilla Premium")
        self.assertEqual(r.status_code, 200, r.data)
        variante.refresh_from_db()
        producto = variante.producto
        producto.refresh_from_db()
        self.assertEqual(producto.nombre, "Mascarilla Premium")
        listado = self.api.get("/api/productos/articulos/", {"search": "Mascarilla Premium"})
        self.assertEqual(listado.status_code, 200, listado.data)
        self.assertEqual(listado.data["results"][0]["nombre_mostrar"], "Mascarilla Premium")

    def test_renombre_nuevo_duplicado_no_revela_nombre_tecnico(self):
        self.nuevo(nombre="Mascarilla Nueva")
        variante2 = self.nuevo(nombre="Mascarilla Nueva")
        r = self.patch(variante2, nombre="Mascarilla Editada")
        self.assertEqual(r.status_code, 200, r.data)
        listado = self.api.get("/api/productos/articulos/", {"search": "Mascarilla Editada"})
        self.assertEqual(listado.status_code, 200, listado.data)
        self.assertEqual(listado.data["results"][0]["nombre_mostrar"], "Mascarilla Editada")

    def test_stock_directo_rechazado_y_sku_persistente(self):
        variante = self.nuevo(sku="SKU-PRUEBA-9")
        r = self.patch(variante, stock=25)
        self.assertEqual(r.status_code, 400, r.data)
        r = self.patch(variante, stock_minimo=3, precio_menudeo="90.00")
        self.assertEqual(r.status_code, 200, r.data)
        variante.refresh_from_db()
        self.assertEqual(variante.sku, "SKU-PRUEBA-9")
        self.assertEqual(variante.stock, 0)

    def test_variante_historica_precio_cero_puede_editar_otros_campos(self):
        producto = Producto.objects.create(nombre="Histórico", categoria=self.categoria)
        variante = Variante.objects.create(producto=producto, nombre="Única", sku="LEGACY0", precio_menudeo=0)
        r = self.patch(variante, stock_minimo=7)
        self.assertEqual(r.status_code, 200, r.data)
        r = self.patch(variante, precio_menudeo="0.00")
        self.assertEqual(r.status_code, 400, r.data)
