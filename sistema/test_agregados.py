"""Pruebas de los Agregados (salsas, más papas, etc.): descuentan insumos como un producto."""
import json
from decimal import Decimal

from django.urls import reverse

from . import services
from .models import (Agregado, DetalleAgregado, Insumo, MovimientoInventario, Pedido, Receta, RecetaAgregado,
                     RegistroAuditoria, Usuario)
from .tests import Base


class AgregadosBase(Base):
    def setUp(self):
        super().setUp()
        self.salsa = Insumo.objects.create(nombre="Salsa verde", unidad="kg", stock_actual=1, stock_minimo=0)
        self.extra = Agregado.objects.create(nombre="Salsa verde", precio=500)
        RecetaAgregado.objects.create(agregado=self.extra, insumo=self.salsa, cantidad_por_unidad=Decimal("0.100"))

    def pedir_con(self, agregados, cant=1):
        return services.crear_pedido(self.garzon, "retiro", {"nombre": "Ana"},
                                     [{"producto": self.prod.pk, "cantidad": cant}], agregados=agregados)


class DescuentoDeAgregadosTests(AgregadosBase):
    def test_el_agregado_descuenta_su_insumo_y_suma_al_total(self):
        pedido = self.pedir_con([{"agregado": self.extra.pk, "cantidad": 3}])
        self.salsa.refresh_from_db()
        self.assertEqual(self.salsa.stock_actual, Decimal("0.70"))
        self.assertEqual(pedido.total, self.prod.precio + 3 * 500)
        self.assertEqual(DetalleAgregado.objects.get(pedido=pedido).precio_unitario, 500)
        self.assertTrue(MovimientoInventario.objects.filter(insumo=self.salsa, tipo="salida", pedido=pedido).exists())

    def test_sin_agregados_todo_sigue_igual(self):
        pedido = self.pedir_con(None)
        self.assertEqual(pedido.total, self.prod.precio)
        self.assertFalse(DetalleAgregado.objects.exists())

    def test_sin_stock_del_agregado_no_se_guarda_nada(self):
        with self.assertRaises(services.ErrorNegocio) as e:
            self.pedir_con([{"agregado": self.extra.pk, "cantidad": 11}])      # necesita 1,1 y hay 1
        self.assertIn("No hay stock suficiente de «Salsa verde»", str(e.exception))
        self.assertEqual(Pedido.objects.count(), 0)
        self.pan.refresh_from_db()
        self.assertEqual(self.pan.stock_actual, 10)                            # tampoco se descontó el pan

    def test_agregado_inactivo_o_inexistente_se_rechaza(self):
        self.extra.activo = False
        self.extra.save()
        with self.assertRaises(services.ErrorNegocio):
            self.pedir_con([{"agregado": self.extra.pk, "cantidad": 1}])
        with self.assertRaises(services.ErrorNegocio):
            self.pedir_con([{"agregado": 999999, "cantidad": 1}])

    def test_cantidades_no_validas_se_rechazan(self):
        for malo in ("-1", "1.5", "abc", "1e3", "100"):
            with self.subTest(malo=malo), self.assertRaises(services.ErrorNegocio):
                self.pedir_con([{"agregado": self.extra.pk, "cantidad": malo}])

    def test_lineas_repetidas_se_suman(self):
        self.pedir_con([{"agregado": self.extra.pk, "cantidad": 1}, {"agregado": self.extra.pk, "cantidad": 2}])
        self.assertEqual(DetalleAgregado.objects.get().cantidad, 3)

    def test_anular_antes_de_preparar_repone_el_stock_del_agregado(self):
        pedido = self.pedir_con([{"agregado": self.extra.pk, "cantidad": 2}])
        services.anular_pedido(pedido, self.garzon, "Se equivocó")
        self.salsa.refresh_from_db()
        self.assertEqual(self.salsa.stock_actual, 1)

    def test_agregado_sin_receta_no_descuenta_nada(self):
        simple = Agregado.objects.create(nombre="Servilletas", precio=0)
        self.pedir_con([{"agregado": simple.pk, "cantidad": 1}])
        self.salsa.refresh_from_db()
        self.assertEqual(self.salsa.stock_actual, 1)


class ApiYCrudDeAgregadosTests(AgregadosBase):
    def test_pantalla_del_garzon_ofrece_agregados_activos(self):
        self.client.force_login(self.garzon)
        response = self.client.get(reverse("garzon"))
        self.assertContains(response, 'id="datos-agregados"')
        self.assertContains(response, "Salsa verde")

    def test_pantalla_de_productos_muestra_gestion_de_agregados(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("productos"))
        self.assertContains(response, "Agregados")
        self.assertContains(response, "Salsa verde")
        self.assertContains(response, reverse("agregado_crear"))

    def test_api_de_pedidos_acepta_agregados(self):
        self.client.force_login(self.garzon)
        r = self.client.post(reverse("api_pedido_crear"), json.dumps({
            "canal": "retiro", "datos": {"nombre": "Ana"},
            "items": [{"producto": self.prod.pk, "cantidad": 1}],
            "agregados": [{"agregado": self.extra.pk, "cantidad": 2}]}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.salsa.refresh_from_db()
        self.assertEqual(self.salsa.stock_actual, Decimal("0.80"))

    def test_la_comanda_de_cocina_muestra_el_agregado(self):
        self.pedir_con([{"agregado": self.extra.pk, "cantidad": 2}])
        self.client.force_login(self.cocina)
        items = self.client.get(reverse("api_comandas")).json()["comandas"][0]["items"]
        extra = [i for i in items if i["n"].startswith("+")][0]
        self.assertEqual((extra["n"], extra["c"]), ("+ Salsa verde", 2))
        self.assertEqual(extra["ins"][0]["c"], "0.2")

    def test_solo_el_admin_gestiona_agregados(self):
        for u in (self.garzon, self.cocina):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("agregado_crear")).status_code, 403)

    def test_admin_crea_edita_y_elimina_un_agregado(self):
        admin = Usuario.objects.create_user("jefe", password="x", rol="admin")
        self.client.force_login(admin)
        datos = {"nombre": "Más papas", "precio": "1200", "activo": "on",
                 "recetas-TOTAL_FORMS": "1", "recetas-INITIAL_FORMS": "0",
                 "recetas-MIN_NUM_FORMS": "0", "recetas-MAX_NUM_FORMS": "1000",
                 "recetas-0-insumo": self.salsa.pk, "recetas-0-cantidad_por_unidad": "0,05"}
        r = self.client.post(reverse("agregado_crear"), datos)
        self.assertRedirects(r, reverse("productos"))
        nuevo = Agregado.objects.get(nombre="Más papas")
        self.assertEqual(nuevo.recetas.get().cantidad_por_unidad, Decimal("0.05"))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="agregado_creado").exists())
        self.assertContains(self.client.get(reverse("agregado_editar", args=[nuevo.pk])), "Más papas")
        self.assertEqual(self.client.get(reverse("productos")).status_code, 200)
        self.client.post(reverse("agregado_eliminar", args=[nuevo.pk]))
        self.assertFalse(Agregado.objects.filter(pk=nuevo.pk).exists())

    def test_precio_con_letras_se_rechaza(self):
        admin = Usuario.objects.create_user("jefe", password="x", rol="admin")
        self.client.force_login(admin)
        r = self.client.post(reverse("agregado_crear"), {
            "nombre": "X", "precio": "12abc", "recetas-TOTAL_FORMS": "0", "recetas-INITIAL_FORMS": "0",
            "recetas-MIN_NUM_FORMS": "0", "recetas-MAX_NUM_FORMS": "1000"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Agregado.objects.filter(nombre="X").exists())
