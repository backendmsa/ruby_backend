"""Pruebas de operaciones de inventario con motivos opcionales y stock real."""
from django.test import TestCase
from rest_framework.test import APIClient
from categorias.models import Categoria
from productos.models import Producto
from variantes.models import Variante
from usuarios.models import Usuario
from inventario.models import MovimientoInventario


class InventarioOpcionalTests(TestCase):
    def setUp(self):
        categoria=Categoria.objects.create(nombre="INVENTARIO PRUEBAS OPCIONAL")
        producto=Producto.objects.create(categoria=categoria,nombre="Artículo inventario test")
        self.variante=Variante.objects.create(producto=producto,nombre="Unidad",sku="INVE-OP-1",stock=14)
        self.usuario=Usuario.objects.create_user(
            usuario="inventario_pruebas",email="inventario_pruebas@example.test",
            password="Pruebas#123",nombre="Prueba",apellido="Inventario",rol=1,
        )
        self.api=APIClient()
        self.api.force_authenticate(user=self.usuario)

    def test_ajuste_disminuye_a_existencia_real_sin_motivo(self):
        response=self.api.post('/api/inventario/ajuste/', {
            'variante_id':str(self.variante.id),'stock_nuevo':10,
        },format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock,10)
        mov=MovimientoInventario.objects.get(variante=self.variante,tipo='AJUSTE')
        self.assertEqual((mov.stock_anterior,mov.cantidad,mov.stock_nuevo),(14,4,10))
        self.assertIn('DISMINUCIÓN',mov.observaciones)
        history=self.api.get('/api/inventario/',{'variante_id':str(self.variante.id)})
        self.assertEqual(history.status_code,200,history.data)
        self.assertEqual(history.data['results'][0]['stock_nuevo'],10)
        self.assertEqual(history.data['results'][0]['cantidad'],4)

    def test_ajuste_aumenta_a_existencia_real_con_motivo(self):
        response=self.api.post('/api/inventario/ajuste/', {
            'variante_id':str(self.variante.id),'stock_nuevo':20,
            'observaciones':'  Conteo físico  ',
        },format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock,20)
        mov=MovimientoInventario.objects.get(variante=self.variante,tipo='AJUSTE')
        self.assertEqual((mov.stock_anterior,mov.cantidad,mov.stock_nuevo),(14,6,20))
        self.assertIn('Conteo físico',mov.observaciones)

    def test_entrada_sin_observaciones(self):
        response=self.api.post('/api/inventario/entrada/', {
            'variante_id':str(self.variante.id),'cantidad':5,
        },format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock,19)
        mov=MovimientoInventario.objects.get(variante=self.variante,tipo='ENTRADA')
        self.assertEqual((mov.stock_anterior,mov.cantidad,mov.stock_nuevo),(14,5,19))
        self.assertEqual(mov.observaciones,'')

    def test_salida_observacion_vacia(self):
        response=self.api.post('/api/inventario/salida/', {
            'variante_id':str(self.variante.id),'cantidad':5,'observaciones':'',
        },format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock,9)
        mov=MovimientoInventario.objects.get(variante=self.variante,tipo='SALIDA')
        self.assertEqual((mov.stock_anterior,mov.cantidad,mov.stock_nuevo),(14,5,9))

    def test_ajuste_igual_no_crea_movimiento(self):
        response=self.api.post('/api/inventario/ajuste/', {
            'variante_id':str(self.variante.id),'stock_nuevo':14,
        },format='json')
        self.assertEqual(response.status_code,400,response.data)
        self.assertFalse(MovimientoInventario.objects.exists())

    def test_observacion_no_texto_no_modifica_inventario(self):
        response=self.api.post('/api/inventario/entrada/', {
            'variante_id':str(self.variante.id),'cantidad':5,'observaciones':12,
        },format='json')
        self.assertEqual(response.status_code,400,response.data)
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock,14)
        self.assertFalse(MovimientoInventario.objects.exists())
