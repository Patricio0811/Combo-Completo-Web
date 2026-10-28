import json
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from . import services
from .models import (AlertaStock, Comanda, Insumo, Pedido, Producto, Receta,
                     RegistroAuditoria, Usuario)


class Base(TestCase):
    def setUp(self):
        mk = lambda n: Usuario.objects.create_user(n, password="x", rol=n)
        self.garzon, self.cocina, self.cajero, self.admin = (mk(n) for n in ("garzon", "cocina", "cajero", "admin"))
        self.pan = Insumo.objects.create(nombre="Pan", stock_actual=10, stock_minimo=8)
        self.prod = Producto.objects.create(nombre="Completo", precio=3000)
        Receta.objects.create(producto=self.prod, insumo=self.pan, cantidad_por_unidad=1)

    def pedir(self, canal="local", datos=None, cant=1):
        datos = datos if datos is not None else {"mesa": "4"}
        with self.captureOnCommitCallbacks(execute=True):
            return services.crear_pedido(self.garzon, canal, datos, [{"producto": self.prod.pk, "cantidad": cant}])


class PedidoTests(Base):
    def test_canal_obligatorio_y_explicito(self):
        for canal in (None, "", "mesa"):
            with self.assertRaises(services.ErrorNegocio):
                services.crear_pedido(self.garzon, canal, {}, [{"producto": self.prod.pk, "cantidad": 1}])
        self.assertEqual(Pedido.objects.count(), 0)

    def test_tres_canales_por_herencia(self):
        self.assertEqual(self.pedir("local").canal, "Local")
        self.assertEqual(self.pedir("retiro", {"nombre": "Ana"}).canal, "Retiro")
        p = self.pedir("domicilio", {"nombre": "Luis", "telefono": "999", "direccion": "Calle 1", "envio": "1000"})
        self.assertEqual((p.canal, p.total), ("Domicilio", Decimal(4000)))

    def test_pedido_y_comanda_se_guardan_juntos(self):
        with self.assertRaises(services.ErrorNegocio):
            services.crear_pedido(self.garzon, "local", {"mesa": "1"}, [{"producto": 9999, "cantidad": 1}])
        self.assertEqual((Pedido.objects.count(), Comanda.objects.count()), (0, 0))

    def test_stock_se_descuenta_y_genera_alerta_una_vez(self):
        self.pedir(cant=3)
        self.pan.refresh_from_db()
        self.assertEqual(self.pan.stock_actual, 7)
        self.pedir()
        self.assertEqual(AlertaStock.objects.filter(atendida=False).count(), 1)

    def test_datos_del_cliente_van_cifrados_en_la_base(self):
        self.pedir("domicilio", {"nombre": "Luis", "telefono": "+56911112222", "direccion": "Calle Secreta 123"})
        with connection.cursor() as c:
            c.execute("SELECT telefono, direccion FROM sistema_cliente")
            tel, dire = c.fetchone()
        self.assertNotIn("Secreta", dire)
        self.assertNotIn("911112222", tel)
        self.assertEqual(Pedido.objects.get().pedidodomicilio.cliente.direccion, "Calle Secreta 123")

    def test_anular_repone_stock_y_audita(self):
        p = self.pedir(cant=2)
        services.anular_pedido(p, self.admin, "cliente se fue")
        self.pan.refresh_from_db()
        self.assertEqual(self.pan.stock_actual, 10)
        self.assertTrue(RegistroAuditoria.objects.filter(accion="anulacion_pedido").exists())


class PermisosYApiTests(Base):
    def test_roles_restringen_pantallas(self):
        self.client.force_login(self.garzon)
        self.assertEqual(self.client.get(reverse("garzon")).status_code, 200)
        for nombre in ("cocina", "caja", "inventario", "reportes", "auditoria"):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)
        self.client.force_login(self.admin)
        for nombre in ("garzon", "cocina", "caja", "inventario", "reportes", "auditoria"):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)

    def test_sin_sesion_redirige_al_login(self):
        self.assertEqual(self.client.get(reverse("cocina")).status_code, 302)

    def test_api_pedido_y_cocina_ordenada_por_llegada(self):
        self.client.force_login(self.garzon)
        ids = []
        for mesa in ("1", "2", "3"):
            r = self.client.post(reverse("api_pedido_crear"), json.dumps(
                {"canal": "local", "datos": {"mesa": mesa}, "observaciones": "<script>alert(1)</script>",
                 "items": [{"producto": self.prod.pk, "cantidad": 1}]}), content_type="application/json")
            self.assertEqual(r.status_code, 200)
            ids.append(r.json()["id"])
        r = self.client.post(reverse("api_pedido_crear"), json.dumps({"canal": None, "items": []}), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.client.force_login(self.cocina)
        data = self.client.get(reverse("api_comandas")).json()["comandas"]
        self.assertEqual([c["pedido"] for c in data], ids)
        self.assertEqual(data[0]["obs"], "<script>alert(1)</script>")  # se entrega como texto; el JS usa textContent

    def test_flujo_cocina_avisa_al_garzon(self):
        p = self.pedir()
        self.client.force_login(self.cocina)
        c = p.comanda
        for estado in ("preparacion", "lista"):
            self.assertEqual(self.client.post(reverse("api_comanda_estado", args=[c.pk]),
                             json.dumps({"estado": estado}), content_type="application/json").status_code, 200)
        self.assertEqual(self.client.post(reverse("api_comanda_estado", args=[c.pk]),
                         json.dumps({"estado": "preparacion"}), content_type="application/json").status_code, 400)
        self.client.force_login(self.garzon)
        self.assertEqual(len(self.client.get(reverse("api_listos")).json()["listos"]), 1)


class CajaYReportesTests(Base):
    def test_cierre_de_caja_por_metodo(self):
        p = self.pedir(cant=2)  # 6000
        services.registrar_pago(p, "efectivo", Decimal(4000), self.cajero)
        services.registrar_pago(p, "tarjeta", Decimal(2000), self.cajero)
        with self.assertRaises(services.ErrorNegocio):
            services.registrar_pago(p, "efectivo", Decimal(1), self.cajero)  # supera el saldo
        c = services.cerrar_caja(self.cajero, {"efectivo": "3500", "tarjeta": "2000", "transferencia": "0"})
        self.assertEqual((c.monto_esperado, c.diferencia), (6000, -500))
        self.assertEqual(c.desglose["efectivo"]["diferencia"], "-500")
        self.assertTrue(RegistroAuditoria.objects.filter(accion="cierre_caja_con_diferencia").exists())
        self.assertEqual(sum(services.resumen_caja().values()), 0)

    def test_reporte_filtra_por_canal(self):
        self.pedir("local"); self.pedir("retiro", {"nombre": "Ana"}); self.pedir("retiro", {"nombre": "Bo"})
        self.client.force_login(self.admin)
        r = self.client.get(reverse("reportes"), {"canal": "retiro"})
        self.assertEqual((r.context["n"], r.context["total"]), (2, 6000))
        self.assertEqual(self.client.get(reverse("reportes")).context["n"], 3)

    def test_ajuste_manual_de_stock_queda_en_auditoria(self):
        services.ajustar_stock(self.pan, Decimal(5), self.admin, "merma")
        self.assertEqual(RegistroAuditoria.objects.get(accion="ajuste_stock").detalle["motivo"], "merma")
        with self.assertRaises(services.ErrorNegocio):
            services.ajustar_stock(self.pan, Decimal(5), self.admin, " ")
