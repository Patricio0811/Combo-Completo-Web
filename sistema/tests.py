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


class CrudRegistroReportesTests(Base):
    def test_registro_crea_garzon_y_entra(self):
        r = self.client.post(reverse("registro"), {"username": "nuevo", "password1": "Clave-segura-9", "password2": "Clave-segura-9"})
        self.assertEqual(r.status_code, 302)
        u = Usuario.objects.get(username="nuevo")
        self.assertEqual(u.rol, "garzon")
        self.assertEqual(int(self.client.session["_auth_user_id"]), u.pk)

    def test_registro_no_permite_elegir_rol(self):
        self.client.post(reverse("registro"), {"username": "x", "password1": "Clave-segura-9", "password2": "Clave-segura-9", "rol": "admin"})
        self.assertEqual(Usuario.objects.get(username="x").rol, "garzon")

    def test_crud_producto_solo_admin(self):
        self.client.force_login(self.garzon)
        self.assertEqual(self.client.get(reverse("productos")).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.post(reverse("producto_crear"), {"nombre": "Churrasco", "precio": "5000", "activo": "on"})
        self.assertEqual(r.status_code, 302)
        p = Producto.objects.get(nombre="Churrasco")
        self.client.post(reverse("producto_editar", args=[p.pk]), {"nombre": "Churrasco", "precio": "5500", "activo": "on"})
        p.refresh_from_db()
        self.assertEqual(p.precio, 5500)
        self.client.post(reverse("producto_eliminar", args=[p.pk]))
        self.assertFalse(Producto.objects.filter(pk=p.pk).exists())

    def test_validaciones_producto_e_insumo(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("producto_crear"), {"nombre": "Completo", "precio": "0"})
        self.assertContains(r, "Ya existe un producto")
        self.assertContains(r, "mayor que cero")
        r = self.client.post(reverse("insumo_crear"), {"nombre": "Sal", "unidad": "kg", "stock_actual": "-1", "stock_minimo": "0"})
        self.assertContains(r, "no puede ser negativo")

    def test_no_elimina_producto_con_pedidos(self):
        self.pedir()
        self.client.force_login(self.admin)
        self.client.post(reverse("producto_eliminar", args=[self.prod.pk]))
        self.assertTrue(Producto.objects.filter(pk=self.prod.pk).exists())

    def test_reportes_muestra_metricas(self):
        self.pedir()
        self.client.force_login(self.admin)
        r = self.client.get(reverse("reportes"))
        self.assertContains(r, "Ticket promedio")
        self.assertEqual(r.context["n"], 1)
        self.assertEqual(r.context["por_canal"][0]["pedidos"], 1)

    def test_caja_lista_solo_saldo_pendiente(self):
        p = self.pedir()
        self.client.force_login(self.cajero)
        self.assertEqual(len(self.client.get(reverse("caja")).context["pendientes"]), 1)
        services.registrar_pago(p, "efectivo", p.total, self.cajero)
        self.assertEqual(len(self.client.get(reverse("caja")).context["pendientes"]), 0)


class ValidacionNumericaTests(Base):
    """Costos, montos y cantidades: solo números (ni letras, ni símbolos, ni NaN, ni notación científica)."""
    MALOS = ["abc", "12abc", "$1000", "1.000", "1e3", "NaN", "Infinity", "-5", "1 000", "²", "1000000000"]

    def test_costo_de_envio_rechaza_letras_y_simbolos(self):
        for malo in self.MALOS:
            with self.assertRaises(services.ErrorNegocio, msg=malo):
                services.crear_pedido(self.garzon, "domicilio",
                                      {"nombre": "L", "telefono": "1", "direccion": "D", "envio": malo},
                                      [{"producto": self.prod.pk, "cantidad": 1}])
        self.assertEqual(Pedido.objects.count(), 0)

    def test_mesa_solo_digitos_normales(self):
        for malo in ("abc", "²", "1a", "-1"):
            with self.assertRaises(services.ErrorNegocio, msg=malo):
                services.crear_pedido(self.garzon, "local", {"mesa": malo}, [{"producto": self.prod.pk, "cantidad": 1}])

    def test_lectores_numericos(self):
        self.assertEqual(services.leer_entero("4500"), 4500)
        self.assertEqual(services.leer_decimal("2,5"), Decimal("2.5"))
        self.assertEqual(services.leer_decimal("3.25"), Decimal("3.25"))
        for malo in self.MALOS + [""]:
            with self.assertRaises(services.ErrorNegocio, msg=malo):
                services.leer_entero(malo)
        for malo in ("abc", "1e3", "NaN", "-1", "1,234", "1,,2", ""):
            with self.assertRaises(services.ErrorNegocio, msg=malo):
                services.leer_decimal(malo)

    def test_monto_de_pago_en_caja_rechaza_texto(self):
        p = self.pedir(cant=2)
        self.client.force_login(self.cajero)
        for malo in ("12abc", "NaN", "$100", "1e2"):
            r = self.client.post(reverse("caja"), {"accion": "pago", "pedido": p.pk, "metodo": "efectivo", "monto": malo}, follow=True)
            self.assertContains(r, "solo números")
        self.assertEqual(p.pagos.count(), 0)

    def test_cierre_rechaza_montos_con_letras(self):
        self.pedir()
        with self.assertRaises(services.ErrorNegocio):
            services.cerrar_caja(self.cajero, {"efectivo": "10x", "tarjeta": "0", "transferencia": "0"})

    def test_inventario_rechaza_cantidades_invalidas(self):
        self.client.force_login(self.admin)
        for accion, extra in (("entrada", {"cantidad": "abc"}), ("ajuste", {"nuevo": "NaN", "motivo": "x"})):
            r = self.client.post(reverse("inventario"), {"accion": accion, "insumo": self.pan.pk, **extra}, follow=True)
            self.assertContains(r, "solo números")
        self.pan.refresh_from_db()
        self.assertEqual(self.pan.stock_actual, 10)

    def test_precio_de_producto_rechaza_notacion_cientifica_y_texto(self):
        self.client.force_login(self.admin)
        for malo in ("1e3", "abc", "35.00", "$500", "1000000000"):
            r = self.client.post(reverse("producto_crear"), {"nombre": f"P{malo}", "precio": malo, "activo": "on"})
            self.assertEqual(r.status_code, 200, malo)          # vuelve al formulario con error
            self.assertFalse(Producto.objects.filter(nombre=f"P{malo}").exists(), malo)

    def test_insumo_acepta_coma_y_rechaza_texto(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("insumo_crear"), {"nombre": "Sal", "unidad": "kg", "stock_actual": "2,5", "stock_minimo": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Insumo.objects.get(nombre="Sal").stock_actual, Decimal("2.5"))
        for malo in ("1e3", "abc", "NaN"):
            r = self.client.post(reverse("insumo_crear"), {"nombre": f"I{malo}", "unidad": "kg", "stock_actual": malo, "stock_minimo": "1"})
            self.assertEqual(r.status_code, 200, malo)
            self.assertFalse(Insumo.objects.filter(nombre=f"I{malo}").exists(), malo)

    def test_pantallas_cargan_validacion_y_menu_activo(self):
        self.client.force_login(self.admin)
        g = self.client.get(reverse("garzon"))
        self.assertContains(g, 'data-tipo="entero"')
        self.assertContains(g, "validacion.js")
        self.assertContains(self.client.get(reverse("caja")), 'data-tipo="entero"')
        self.assertContains(self.client.get(reverse("inventario")), 'data-tipo="decimal"')
        self.assertContains(self.client.get(reverse("producto_crear")), 'data-tipo="entero"')
        self.assertContains(self.client.get(reverse("productos")), 'aria-current="page"')
