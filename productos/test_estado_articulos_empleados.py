"""Gestión de estado de artículos por empleados (BD aislada de pruebas)."""
from django.test import TestCase
from rest_framework.test import APIClient

from categorias.models import Categoria
from productos.models import Producto
from usuarios.models import Usuario
from variantes.models import Variante
from inventario.models import MovimientoInventario


class EstadoArticulosEmpleadoTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="PRUEBAS ESTADO")
        self.producto = Producto.objects.create(
            categoria=self.categoria, nombre="Artículo pruebas estado"
        )
        self.variante_activa = Variante.objects.create(
            producto=self.producto, nombre="Activa", sku="ESTADO-ACT", stock=12,
        )
        self.variante_inactiva = Variante.objects.create(
            producto=self.producto, nombre="Inactiva", sku="ESTADO-INACT", activo=False,
            stock=5,
        )
        self.empleado = Usuario.objects.create_user(
            usuario="empleado_estados", email="estados_empleado@pruebas.example",
            password="ClavePruebas#123", nombre="Empleado", apellido="Estados", rol=2,
        )
        self.admin = Usuario.objects.create_user(
            usuario="admin_estados", email="estados_admin@pruebas.example",
            password="ClavePruebas#123", nombre="Admin", apellido="Estados", rol=1,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.empleado)
        self.url = "/api/productos/articulos/"

    def test_empleado_puede_listar_todos_activos_e_inactivos(self):
        for filtro, esperado in (("todos", 2), ("true", 1), ("false", 1)):
            with self.subTest(filtro=filtro):
                respuesta = self.api.get(self.url, {"activo": filtro, "page_size": 10})
                self.assertEqual(respuesta.status_code, 200, respuesta.data)
                self.assertEqual(respuesta.data["count"], esperado)
        respuesta = self.api.get(self.url, {"activo": "false"})
        self.assertEqual(respuesta.data["results"][0]["variante_id"], str(self.variante_inactiva.pk))

    def test_empleado_desactiva_y_reactiva_variante_sin_mover_stock(self):
        inicial = MovimientoInventario.objects.count()
        pk = self.variante_activa.pk
        respuesta = self.api.post(f"/api/variantes/{pk}/desactivar/")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.variante_activa.refresh_from_db()
        self.assertFalse(self.variante_activa.activo)
        respuesta = self.api.post(f"/api/variantes/{pk}/activar/")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.variante_activa.refresh_from_db()
        self.assertTrue(self.variante_activa.activo)
        self.assertEqual(self.variante_activa.stock, 12)
        self.assertEqual(MovimientoInventario.objects.count(), inicial)

    def test_empleado_inactivo_no_puede_cambiar_estado(self):
        self.empleado.activo = False
        self.empleado.save(update_fields=["activo"])
        respuesta = self.api.post(f"/api/variantes/{self.variante_inactiva.pk}/activar/")
        self.assertEqual(respuesta.status_code, 403, respuesta.data)
        self.variante_inactiva.refresh_from_db()
        self.assertFalse(self.variante_inactiva.activo)

    def test_empleado_no_puede_activar_producto_padre(self):
        self.producto.activo = False
        self.producto.save(update_fields=["activo"])
        respuesta = self.api.post(f"/api/productos/{self.producto.pk}/activar/")
        self.assertEqual(respuesta.status_code, 403, respuesta.data)
        respuesta = self.api.post(f"/api/variantes/{self.variante_inactiva.pk}/activar/")
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.variante_inactiva.refresh_from_db()
        self.assertFalse(self.variante_inactiva.activo)

    def test_administrador_conserva_permiso_de_activacion(self):
        self.api.force_authenticate(user=self.admin)
        respuesta = self.api.post(f"/api/variantes/{self.variante_inactiva.pk}/activar/")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.variante_inactiva.refresh_from_db()
        self.assertTrue(self.variante_inactiva.activo)
