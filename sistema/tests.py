import json
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from . import services
from .models import (Cliente, PedidoDomicilio, AlertaStock, Comanda, Insumo, Pedido, Producto, Receta,
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
        for nombre in ("Ana", "Beto", "Carla"):
            r = self.client.post(reverse("api_pedido_crear"), json.dumps(
                {"canal": "retiro", "datos": {"nombre": nombre}, "observaciones": "<script>alert(1)</script>",
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


RECETAS_VACIAS = {"recetas-TOTAL_FORMS": "0", "recetas-INITIAL_FORMS": "0",
                  "recetas-MIN_NUM_FORMS": "0", "recetas-MAX_NUM_FORMS": "1000"}


class CrudRegistroReportesTests(Base):
    def test_ya_no_existe_la_creacion_de_cuentas(self):
        self.assertEqual(self.client.get("/registro/").status_code, 404)
        self.assertNotContains(self.client.get(reverse("login")), "Crear cuenta")
        self.client.post("/registro/", {"username": "x", "password1": "Clave-segura-9", "password2": "Clave-segura-9"})
        self.assertFalse(Usuario.objects.filter(username="x").exists())

    def test_crud_producto_solo_admin(self):
        self.client.force_login(self.garzon)
        self.assertEqual(self.client.get(reverse("productos")).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.post(reverse("producto_crear"), {"nombre": "Churrasco", "precio": "5000", "activo": "on", **RECETAS_VACIAS})
        self.assertEqual(r.status_code, 302)
        p = Producto.objects.get(nombre="Churrasco")
        self.client.post(reverse("producto_editar", args=[p.pk]), {"nombre": "Churrasco", "precio": "5500", "activo": "on", **RECETAS_VACIAS})
        p.refresh_from_db()
        self.assertEqual(p.precio, 5500)
        self.client.post(reverse("producto_eliminar", args=[p.pk]))
        self.assertFalse(Producto.objects.filter(pk=p.pk).exists())

    def test_validaciones_producto_e_insumo(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("producto_crear"), {"nombre": "Completo", "precio": "0", **RECETAS_VACIAS})
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
            r = self.client.post(reverse("producto_crear"), {"nombre": f"P{malo}", "precio": malo, "activo": "on", **RECETAS_VACIAS})
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
        self.assertContains(self.client.get(reverse("garzon")), "validacion.js")
        self.assertContains(self.client.get(reverse("caja")), 'data-tipo="entero"')
        self.assertContains(self.client.get(reverse("inventario")), 'data-tipo="decimal"')
        self.assertContains(self.client.get(reverse("producto_crear")), 'data-tipo="entero"')
        self.assertContains(self.client.get(reverse("productos")), 'aria-current="page"')


class CanalesYCocinaTests(Base):
    def _crear_por_api(self, **extra):
        self.client.force_login(self.garzon)
        cuerpo = {"canal": "retiro", "datos": {"nombre": "Ana"}, "items": [{"producto": self.prod.pk, "cantidad": 2}]}
        cuerpo.update(extra)
        return self.client.post(reverse("api_pedido_crear"), json.dumps(cuerpo), content_type="application/json")

    def test_pantalla_del_garzon_ofrece_solo_retiro_y_domicilio(self):
        self.client.force_login(self.garzon)
        html = self.client.get(reverse("garzon")).content.decode()
        for presente in ('value="retiro"', 'value="domicilio"', "Nombre de quien retira", "Nombre del cliente",
                         "Teléfono", "Dirección", "Costo de envío", 'data-tipo="entero"'):
            self.assertIn(presente, html, presente)
        for ausente in ('value="local"', "Número de mesa", ">Local<", "f-mesa"):
            self.assertNotIn(ausente, html, ausente)

    def test_api_acepta_retiro_y_domicilio(self):
        r = self._crear_por_api(canal="retiro")
        self.assertEqual((r.status_code, r.json()["canal"]), (200, "Retiro"))
        r = self._crear_por_api(canal="domicilio", datos={"nombre": "Luis", "telefono": "+56911112222",
                                                           "direccion": "Calle 1 #23", "envio": "1500"})
        self.assertEqual((r.status_code, r.json()["canal"], r.json()["total"]), (200, "Domicilio", 7500))   # 2 x 3000 + 1500
        d = Pedido.objects.get(pk=r.json()["id"]).pedidodomicilio
        self.assertEqual((d.cliente.nombre, d.cliente.telefono, d.cliente.direccion, d.costo_envio),
                         ("Luis", "+56911112222", "Calle 1 #23", Decimal(1500)))

    def test_api_rechaza_local_y_canal_ausente(self):
        for canal in ("local", "mesa", "", None, 5):
            r = self._crear_por_api(canal=canal)
            self.assertEqual(r.status_code, 400, repr(canal))
        self.assertEqual(Pedido.objects.count(), 0)

    def test_domicilio_exige_datos_y_costo_numerico(self):
        base = {"nombre": "Luis", "telefono": "999", "direccion": "Calle 1", "envio": "1000"}
        for campo in ("nombre", "telefono", "direccion"):
            self.assertEqual(self._crear_por_api(canal="domicilio", datos={**base, campo: " "}).status_code, 400, campo)
        for malo in ("abc", "1e3", "NaN", "-5", "$100", "1.000"):
            self.assertEqual(self._crear_por_api(canal="domicilio", datos={**base, "envio": malo}).status_code, 400, malo)
        self.assertEqual(Pedido.objects.count(), 0)

    def test_api_exige_nombre_de_quien_retira(self):
        self.client.force_login(self.garzon)
        r = self.client.post(reverse("api_pedido_crear"), json.dumps(
            {"canal": "retiro", "datos": {"nombre": "  "}, "items": [{"producto": self.prod.pk, "cantidad": 1}]}), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Pedido.objects.count(), 0)

    def test_cocina_recibe_detalle_e_insumos_de_cada_producto(self):
        self.prod.detalle = "Pan, vienesa y palta."
        self.prod.save()
        self._crear_por_api()
        self.client.force_login(self.cocina)
        item = self.client.get(reverse("api_comandas")).json()["comandas"][0]["items"][0]
        self.assertEqual((item["n"], item["c"], item["d"]), ("Completo", 2, "Pan, vienesa y palta."))
        self.assertEqual(item["ins"], [{"n": "Pan", "c": "2", "u": "un"}])

    def test_pantalla_de_cocina_permite_ampliar_la_comanda(self):
        self.client.force_login(self.cocina)
        self.assertContains(self.client.get(reverse("cocina")), "cocina.js")
        js = (__import__("pathlib").Path(__file__).parent / "static/sistema/cocina.js").read_text()
        self.assertIn("Ver detalle", js)
        self.assertIn("abiertas", js)     # recuerda qué comandas están ampliadas entre actualizaciones


class ProductoConRecetaTests(Base):
    def _form(self, filas, **extra):
        datos = {"nombre": "Italiano XL", "precio": "4500", "detalle": "Doble vienesa con palta", "activo": "on",
                 "recetas-TOTAL_FORMS": str(len(filas)), "recetas-INITIAL_FORMS": "0",
                 "recetas-MIN_NUM_FORMS": "0", "recetas-MAX_NUM_FORMS": "1000", **extra}
        for i, (insumo, cant) in enumerate(filas):
            datos[f"recetas-{i}-insumo"] = insumo
            datos[f"recetas-{i}-cantidad_por_unidad"] = cant
        return datos

    def setUp(self):
        super().setUp()
        self.sal = Insumo.objects.create(nombre="Sal", unidad="kg", stock_actual=5, stock_minimo=1)
        self.client.force_login(self.admin)

    def test_crear_producto_con_detalle_y_recetas(self):
        r = self.client.post(reverse("producto_crear"), self._form([(self.pan.pk, "2"), (self.sal.pk, "0,05")]))
        self.assertEqual(r.status_code, 302)
        p = Producto.objects.get(nombre="Italiano XL")
        self.assertEqual(p.detalle, "Doble vienesa con palta")
        self.assertEqual({r_.insumo_id: r_.cantidad_por_unidad for r_ in p.recetas.all()},
                         {self.pan.pk: Decimal("2"), self.sal.pk: Decimal("0.05")})

    def test_el_producto_nuevo_descuenta_stock_segun_su_receta(self):
        self.client.post(reverse("producto_crear"), self._form([(self.pan.pk, "2")]))
        p = Producto.objects.get(nombre="Italiano XL")
        with self.captureOnCommitCallbacks(execute=True):
            services.crear_pedido(self.garzon, "retiro", {"nombre": "Ana"}, [{"producto": p.pk, "cantidad": 3}])
        self.pan.refresh_from_db()
        self.assertEqual(self.pan.stock_actual, 4)   # 10 - (2 x 3)

    def test_filas_vacias_se_ignoran(self):
        r = self.client.post(reverse("producto_crear"), self._form([("", ""), (self.pan.pk, "1"), ("", "")]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Producto.objects.get(nombre="Italiano XL").recetas.count(), 1)

    def test_rechaza_insumo_repetido_y_cantidades_invalidas(self):
        r = self.client.post(reverse("producto_crear"), self._form([(self.pan.pk, "1"), (self.pan.pk, "2")]))
        self.assertContains(r, "está repetido")
        for malo in ("abc", "1e3", "NaN", "0", "-1", "1,2345"):
            r = self.client.post(reverse("producto_crear"), self._form([(self.pan.pk, malo)]))
            self.assertEqual(r.status_code, 200, malo)
        self.assertFalse(Producto.objects.filter(nombre="Italiano XL").exists())   # nada se guarda a medias

    def test_editar_cambia_y_quita_insumos(self):
        self.client.post(reverse("producto_crear"), self._form([(self.pan.pk, "1"), (self.sal.pk, "1")]))
        p = Producto.objects.get(nombre="Italiano XL")
        r1, r2 = list(p.recetas.order_by("pk"))
        datos = self._form([(self.pan.pk, "3"), (self.sal.pk, "1")], detalle="Nuevo detalle")
        datos.update({"recetas-INITIAL_FORMS": "2", "recetas-0-id": r1.pk, "recetas-1-id": r2.pk,
                      "recetas-1-DELETE": "on", "recetas-0-producto": p.pk, "recetas-1-producto": p.pk})
        self.assertEqual(self.client.post(reverse("producto_editar", args=[p.pk]), datos).status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.detalle, "Nuevo detalle")
        self.assertEqual([(x.insumo_id, x.cantidad_por_unidad) for x in p.recetas.all()], [(self.pan.pk, Decimal("3"))])

    def test_formulario_muestra_caja_de_detalle_y_tabla_de_insumos(self):
        html = self.client.get(reverse("producto_crear")).content.decode()
        self.assertIn("<textarea", html)
        self.assertIn("Insumos que usa", html)
        self.assertIn("recetas-TOTAL_FORMS", html)
        self.assertIn("receta.js", html)

    def test_lista_de_productos_muestra_detalle_e_insumos(self):
        self.prod.detalle = "Pan con vienesa"
        self.prod.save()
        html = self.client.get(reverse("productos")).content.decode()
        self.assertIn("Pan con vienesa", html)
        self.assertIn("Pan (1", html)


class InventarioYCifradoTests(Base):
    def test_inventario_tiene_un_solo_boton_nuevo_insumo(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("inventario")).content.decode()
        self.assertEqual(html.count("Nuevo insumo</a>"), 1)

    def _cliente_con_clave(self, clave):
        from django.test import override_settings
        with override_settings(FIELD_ENCRYPTION_KEY=clave):
            return Cliente.objects.create(nombre="Luis", telefono="+56911112222", direccion="Calle 1 #23")

    def test_dato_cifrado_con_otra_clave_no_tumba_la_aplicacion(self):
        """Bug InvalidToken: antes cualquier pantalla que leyera ese cliente respondía error 500."""
        from cryptography.fernet import Fernet
        from django.test import override_settings
        from .campos import DATO_NO_LEGIBLE
        c = self._cliente_con_clave(Fernet.generate_key().decode())
        ped = PedidoDomicilio.objects.create(cliente=c, costo_envio=0, usuario=self.garzon)
        Comanda.objects.create(pedido=ped)
        with override_settings(FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode()):   # la clave actual es otra
            leido = Cliente.objects.get(pk=c.pk)
            self.assertEqual((leido.nombre, leido.telefono), ("Luis", DATO_NO_LEGIBLE))
            self.client.force_login(self.cocina)
            self.assertEqual(self.client.get(reverse("api_comandas")).status_code, 200)       # la cocina sigue funcionando
            self.client.force_login(self.admin)
            self.assertEqual(self.client.get(reverse("reportes")).status_code, 200)
            with self.assertRaises(ValueError):                                              # no se sobrescribe con el aviso
                leido.save()

    def test_rotacion_de_claves_permite_leer_datos_antiguos(self):
        from cryptography.fernet import Fernet
        from django.test import override_settings
        vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        c = self._cliente_con_clave(vieja)
        with override_settings(FIELD_ENCRYPTION_KEY=f"{nueva},{vieja}"):                      # la primera cifra, todas descifran
            self.assertEqual(Cliente.objects.get(pk=c.pk).telefono, "+56911112222")

    def test_secret_key_anterior_recupera_datos_y_el_comando_los_recifra(self):
        import os
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        from django.test import override_settings
        with override_settings(SECRET_KEY="clave-antigua-que-ya-no-se-usa", FIELD_ENCRYPTION_KEY=None):
            c = Cliente.objects.create(nombre="Ana", telefono="12345", direccion="Calle 9")
        with override_settings(SECRET_KEY="clave-nueva", FIELD_ENCRYPTION_KEY=None):
            self.assertNotEqual(Cliente.objects.get(pk=c.pk).telefono, "12345")               # sin la clave antigua: ilegible
            with mock.patch.dict(os.environ, {"DJANGO_SECRET_KEY_ANTERIORES": "clave-antigua-que-ya-no-se-usa"}):
                self.assertEqual(Cliente.objects.get(pk=c.pk).telefono, "12345")             # con ella: se lee
                call_command("reencriptar_clientes", stdout=StringIO())
            self.assertEqual(Cliente.objects.get(pk=c.pk).direccion, "Calle 9")              # ya sin la clave antigua
