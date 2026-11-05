"""Pruebas de seguridad: inyección SQL, XSS y CSRF.
Cada prueba ataca el sistema con payloads reales y comprueba que no tengan efecto."""
import json
import re
from html.parser import HTMLParser

from django.db import connection
from django.test import Client
from django.urls import reverse

from . import services
from .models import (Comanda, Insumo, Pago, Pedido, Producto, Receta, RegistroAuditoria, Usuario)
from .tests import Base

MARCA = "XSS-7731"
XSS = [
    f'<script>alert("{MARCA}")</script>',
    f'"><img src=x onerror=alert("{MARCA}")>',
    f"'-alert('{MARCA}')-'",
    f'</script><script>alert("{MARCA}")</script>',
    f'<svg onload=alert("{MARCA}")>',
]
SQLI = ["' OR '1'='1", "' OR 1=1--", "1; DROP TABLE sistema_pedido;--", "' UNION SELECT username,password FROM sistema_usuario--",
        '" OR ""="', "1 OR 1=1", "'; DELETE FROM sistema_producto;--"]
TABLAS = ("sistema_pedido", "sistema_producto", "sistema_usuario", "sistema_insumo", "sistema_pago")


class _Detector(HTMLParser):
    """Analiza el HTML como lo haría un navegador y anota todo lo que el payload logró volver ACTIVO:
    etiquetas <img src=x>/<svg>, atributos on*="...payload..." y scripts ejecutables que contengan la marca.
    El texto escapado (&lt;script&gt;) es inerte y no cuenta."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hallazgos, self._script = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "svg" or (tag == "img" and a.get("src") == "x"):
            self.hallazgos.append(f"etiqueta inyectada <{tag}>")
        for nombre, valor in attrs:
            if nombre.startswith("on") and MARCA in (valor or ""):
                self.hallazgos.append(f"atributo {nombre} inyectado")
        if tag == "script":
            self._script = a.get("type", "")

    def handle_data(self, data):
        if self._script is not None and self._script != "application/json" and MARCA in data:
            self.hallazgos.append("script ejecutable con el payload")

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = None


def hallazgos_xss(html):
    d = _Detector(); d.feed(html); d.close()
    return d.hallazgos


def sin_xss(html):
    return not hallazgos_xss(html)


def contar_tablas():
    with connection.cursor() as c:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLAS}


# ====================================================================== CSRF
class CsrfTests(Base):
    """Un POST sin token CSRF válido debe rechazarse (403) y no cambiar nada."""

    def setUp(self):
        super().setUp()
        self.p = self.pedir("retiro", {"nombre": "Ana"}, cant=2)
        self.c = Client(enforce_csrf_checks=True)       # el cliente de pruebas normal se salta el CSRF
        self.json = {"content_type": "application/json"}

    def _rechaza(self, usuario, url, datos=None, **kw):
        self.c.force_login(usuario)
        antes = contar_tablas()
        r = self.c.post(url, datos or {}, **kw)
        self.assertEqual(r.status_code, 403, f"{url} aceptó un POST sin token CSRF")
        self.assertEqual(contar_tablas(), antes, f"{url} modificó datos sin token CSRF")

    def test_apis_json_rechazan_post_sin_token(self):
        cuerpo = json.dumps({"canal": "retiro", "datos": {"nombre": "X"}, "items": [{"producto": self.prod.pk, "cantidad": 1}]})
        self._rechaza(self.garzon, reverse("api_pedido_crear"), cuerpo, **self.json)
        self._rechaza(self.garzon, reverse("api_entregar", args=[self.p.pk]))
        self._rechaza(self.cocina, reverse("api_comanda_estado", args=[self.p.comanda.pk]), json.dumps({"estado": "preparacion"}), **self.json)
        self.assertEqual(Comanda.objects.get(pk=self.p.comanda.pk).estado, "pendiente")

    def test_formularios_de_caja_e_inventario_rechazan_post_sin_token(self):
        self._rechaza(self.cajero, reverse("caja"), {"accion": "pago", "pedido": self.p.pk, "metodo": "efectivo", "monto": "100"})
        self._rechaza(self.cajero, reverse("caja"), {"accion": "cierre", "contado_efectivo": "0"})
        self._rechaza(self.admin, reverse("caja"), {"accion": "anular", "pedido": self.p.pk, "motivo": "x"})
        self._rechaza(self.admin, reverse("inventario"), {"accion": "entrada", "insumo": self.pan.pk, "cantidad": "5"})
        self._rechaza(self.admin, reverse("inventario"), {"accion": "ajuste", "insumo": self.pan.pk, "nuevo": "0", "motivo": "x"})
        self.pan.refresh_from_db(); self.assertEqual(self.pan.stock_actual, 8)   # 10 - 2 por el pedido

    def test_crud_rechaza_post_sin_token(self):
        self._rechaza(self.admin, reverse("producto_crear"), {"nombre": "Hack", "precio": "1", "recetas-TOTAL_FORMS": "0", "recetas-INITIAL_FORMS": "0"})
        self._rechaza(self.admin, reverse("producto_editar", args=[self.prod.pk]), {"nombre": "Hack", "precio": "1"})
        self._rechaza(self.admin, reverse("producto_eliminar", args=[self.prod.pk]))
        self._rechaza(self.admin, reverse("insumo_crear"), {"nombre": "Hack", "unidad": "x", "stock_actual": "1", "stock_minimo": "1"})
        self._rechaza(self.admin, reverse("insumo_eliminar", args=[self.pan.pk]))
        self.assertTrue(Producto.objects.filter(pk=self.prod.pk, nombre="Completo").exists())

    def test_login_y_logout_exigen_token(self):
        antes = Usuario.objects.count()
        r = self.c.post(reverse("login"), {"username": "admin", "password": "x"})
        self.assertEqual(r.status_code, 403)
        self.c.force_login(self.admin)
        self.assertEqual(self.c.post(reverse("logout")).status_code, 403)   # logout CSRF
        self.assertEqual(Usuario.objects.count(), antes)

    def test_con_token_valido_si_funciona(self):
        """Comprueba que la protección no rompe el uso normal: el JS lee la cookie csrftoken y la envía."""
        self.c.force_login(self.garzon)
        self.c.get(reverse("garzon"))                                    # entrega la cookie csrftoken
        token = self.c.cookies["csrftoken"].value
        cuerpo = json.dumps({"canal": "retiro", "datos": {"nombre": "Ana"}, "items": [{"producto": self.prod.pk, "cantidad": 1}]})
        r = self.c.post(reverse("api_pedido_crear"), cuerpo, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        r = self.c.post(reverse("api_pedido_crear"), cuerpo, content_type="application/json", HTTP_X_CSRFTOKEN="token-falso")
        self.assertEqual(r.status_code, 403)

    def test_acciones_que_cambian_datos_no_responden_a_get(self):
        self.client.force_login(self.garzon)
        for nombre, args in (("api_pedido_crear", []), ("api_entregar", [self.p.pk])):
            self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 405, nombre)
        self.client.force_login(self.cocina)
        self.assertEqual(self.client.get(reverse("api_comanda_estado", args=[self.p.comanda.pk])).status_code, 405)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("caja"), {"accion": "anular", "pedido": self.p.pk, "motivo": "x"}).status_code, 200)
        self.p.refresh_from_db(); self.assertNotEqual(self.p.estado, "anulado")

    def test_todos_los_formularios_html_llevan_token(self):
        self.client.force_login(self.admin)
        for nombre, args in (("caja", []), ("inventario", []), ("producto_crear", []), ("insumo_crear", []),
                             ("producto_eliminar", [self.prod.pk]), ("insumo_eliminar", [self.pan.pk])):
            html = self.client.get(reverse(nombre, args=args)).content.decode()
            for form in re.findall(r"<form[^>]*method=\"post\".*?</form>", html, re.S):
                self.assertIn("csrfmiddlewaretoken", form, f"{nombre}: formulario POST sin token")


# ====================================================================== XSS
class DetectorTests(Base):
    def test_el_detector_distingue_html_activo_de_texto_escapado(self):
        self.assertTrue(hallazgos_xss(f'<p>{XSS[0]}</p>'))                                  # script real
        self.assertTrue(hallazgos_xss(f'<input value="{XSS[1]}">'))                         # rompe el atributo
        self.assertTrue(hallazgos_xss(f'<script type="application/json">"{XSS[3]}"</script>'))  # rompe el json
        self.assertTrue(hallazgos_xss(f'<div onclick=alert("{MARCA}")>x</div>'))
        self.assertFalse(hallazgos_xss('<p>&lt;script&gt;alert(&quot;XSS-7731&quot;)&lt;/script&gt;</p>'))
        self.assertFalse(hallazgos_xss('<input value="&quot;&gt;&lt;img src=x onerror=alert(&quot;XSS-7731&quot;)&gt;">'))
        self.assertFalse(hallazgos_xss('<script type="application/json">"\\u003Cscript\\u003Ealert(\\"XSS-7731\\")"</script>'))


class XssTests(Base):
    """Datos hostiles guardados en el sistema nunca deben llegar al navegador como HTML activo."""

    def setUp(self):
        super().setUp()
        self.admin.first_name = XSS[0]; self.admin.save()
        self.client.force_login(self.admin)

    def _todas_las_paginas(self):
        p = Producto.objects.exclude(pk=self.prod.pk).first()
        i = Insumo.objects.exclude(pk=self.pan.pk).first()
        urls = [reverse(n) for n in ("garzon", "cocina", "caja", "inventario", "reportes", "auditoria", "productos",
                                      "producto_crear", "insumo_crear")]
        urls += [reverse("producto_editar", args=[p.pk]), reverse("producto_eliminar", args=[p.pk]),
                 reverse("insumo_editar", args=[i.pk]), reverse("insumo_eliminar", args=[i.pk])]
        return urls

    def test_datos_hostiles_en_toda_la_aplicacion_salen_escapados(self):
        for k, payload in enumerate(XSS):
            prod = Producto.objects.create(nombre=payload, precio=100 + k, detalle=payload, activo=True)
            ins = Insumo.objects.create(nombre=payload, unidad=payload, stock_actual=1, stock_minimo=5)
            Receta.objects.create(producto=prod, insumo=ins, cantidad_por_unidad=1)
            self.client.post(reverse("api_pedido_crear"), json.dumps({"canal": "retiro", "datos": {"nombre": payload}, "observaciones": payload,
                             "items": [{"producto": prod.pk, "cantidad": 1}]}), content_type="application/json")
            services.auditar(self.admin, payload, motivo=payload, otro=payload)
            services.ajustar_stock(ins, 3, self.admin, payload)
        with self.captureOnCommitCallbacks(execute=True):
            pass
        for url in self._todas_las_paginas():
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            html = r.content.decode()
            self.assertEqual(hallazgos_xss(html), [], f"XSS sin escapar en {url}")
        self.assertIn("&lt;script&gt;", self.client.get(reverse("productos")).content.decode())   # escapado, no borrado

    def test_nombre_de_producto_no_rompe_el_json_incrustado_del_garzon(self):
        Producto.objects.create(nombre=XSS[3], precio=1, activo=True)
        html = self.client.get(reverse("garzon")).content.decode()
        bloque = re.search(r'<script id="datos-productos"[^>]*>(.*?)</script>', html, re.S).group(1)
        self.assertNotIn("</script>", bloque)
        self.assertNotIn("<", bloque)                       # json_script escapa < > & como \uXXXX
        self.assertIn(XSS[3], [p["nombre"] for p in json.loads(bloque)])   # y el dato original se conserva

    def test_apis_devuelven_json_no_html_y_con_nosniff(self):
        self.client.post(reverse("api_pedido_crear"), json.dumps({"canal": "retiro", "datos": {"nombre": XSS[1]}, "observaciones": XSS[0],
                         "items": [{"producto": self.prod.pk, "cantidad": 1}]}), content_type="application/json")
        r = self.client.get(reverse("api_comandas"))
        self.assertTrue(r["Content-Type"].startswith("application/json"))
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.json()["comandas"][0]["obs"], XSS[0])        # viaja como texto

    def test_el_javascript_inserta_datos_solo_como_texto(self):
        from pathlib import Path
        js = Path(__file__).parent / "static" / "sistema"
        for archivo in ("cocina.js", "garzon.js", "validacion.js"):
            codigo = (js / archivo).read_text()
            for peligroso in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
                self.assertNotIn(peligroso, codigo, f"{archivo} usa {peligroso}")
        # receta.js clona una <template> escrita por el servidor (ya escapada): no recibe datos de usuarios.
        self.assertIn("innerHTML", (js / "receta.js").read_text())

    def test_formularios_reflejan_el_valor_escapado_al_fallar(self):
        r = self.client.post(reverse("producto_crear"), {"nombre": XSS[1], "precio": "abc", "detalle": XSS[0],
                             "recetas-TOTAL_FORMS": "0", "recetas-INITIAL_FORMS": "0"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(sin_xss(r.content.decode()))

    def test_login_no_refleja_el_usuario_ni_next_sin_escapar(self):
        self.client.logout()
        r = self.client.post(reverse("login") + "?next=" + XSS[0], {"username": XSS[1], "password": "x"})
        self.assertTrue(sin_xss(r.content.decode()))

    def test_cabeceras_anti_clickjacking(self):
        self.assertEqual(self.client.get(reverse("garzon"))["X-Frame-Options"], "DENY")

    def test_next_del_login_no_permite_redireccion_abierta(self):
        self.client.logout()
        for destino in ("https://evil.example/robo", "//evil.example", "javascript:alert(1)"):
            r = self.client.post(reverse("login") + "?next=" + destino, {"username": "admin", "password": "x"})
            self.assertEqual(r.status_code, 302)
            self.assertFalse(r["Location"].startswith(("http", "//", "javascript")), destino)


# ====================================================================== SQL
class InyeccionSqlTests(Base):
    """Los payloads de inyección deben tratarse como texto: sin errores 500, sin filtrar datos y sin borrar tablas."""

    def setUp(self):
        super().setUp()
        self.p = self.pedir("retiro", {"nombre": "Ana"}, cant=2)
        services.auditar(self.admin, "ajuste_stock", motivo="uno")
        services.auditar(self.admin, "anulacion_pedido", motivo="dos")
        self.client.force_login(self.admin)
        self.antes = contar_tablas()

    def _intacto(self):
        self.assertEqual(contar_tablas(), self.antes)

    def test_parametros_get_de_reportes_y_auditoria(self):
        for sqli in SQLI:
            for url, params in ((reverse("reportes"), {"desde": sqli}), (reverse("reportes"), {"hasta": sqli}),
                                (reverse("reportes"), {"canal": sqli}), (reverse("auditoria"), {"accion": sqli})):
                r = self.client.get(url, params)
                self.assertEqual(r.status_code, 200, f"{url} {params}")
        self._intacto()

    def test_filtro_de_auditoria_no_devuelve_todo_con_or_1_igual_1(self):
        todo = self.client.get(reverse("auditoria")).context["registros"]
        self.assertEqual(len(todo), 2)
        for sqli in ("' OR '1'='1", "' OR 1=1--", "x' OR accion LIKE '%"):
            self.assertEqual(len(self.client.get(reverse("auditoria"), {"accion": sqli}).context["registros"]), 0, sqli)

    def test_campos_post_de_caja_e_inventario(self):
        for sqli in SQLI:
            for datos in ({"accion": "pago", "pedido": sqli, "metodo": "efectivo", "monto": "100"},
                          {"accion": "pago", "pedido": self.p.pk, "metodo": sqli, "monto": "100"},
                          {"accion": "pago", "pedido": self.p.pk, "metodo": "efectivo", "monto": sqli},
                          {"accion": "anular", "pedido": sqli, "motivo": sqli},
                          {"accion": "cierre", "contado_efectivo": sqli}):
                r = self.client.post(reverse("caja"), datos, follow=True)
                self.assertIn(r.status_code, (200, 404), str(datos))        # nunca 500
            for datos in ({"accion": "entrada", "insumo": sqli, "cantidad": "1"}, {"accion": "entrada", "insumo": self.pan.pk, "cantidad": sqli},
                          {"accion": "ajuste", "insumo": self.pan.pk, "nuevo": sqli, "motivo": sqli},
                          {"accion": "atender", "alerta": sqli}, {"accion": sqli}):
                r = self.client.post(reverse("inventario"), datos, follow=True)
                self.assertIn(r.status_code, (200, 404), str(datos))        # nunca 500
        self._intacto()
        self.assertEqual(Pago.objects.count(), 0)          # ningún payload se coló como pago válido

    def test_campos_de_crud_y_api_con_payloads(self):
        for sqli in SQLI:
            self.client.post(reverse("insumo_crear"), {"nombre": sqli, "unidad": sqli, "stock_actual": sqli, "stock_minimo": sqli})
            self.client.post(reverse("producto_crear"), {"nombre": sqli, "precio": sqli, "detalle": sqli,
                             "recetas-TOTAL_FORMS": "1", "recetas-INITIAL_FORMS": "0", "recetas-0-insumo": sqli, "recetas-0-cantidad_por_unidad": sqli})
            r = self.client.post(reverse("api_pedido_crear"), json.dumps({"canal": "retiro", "datos": {"nombre": sqli}, "observaciones": sqli,
                                 "items": [{"producto": sqli, "cantidad": sqli}]}), content_type="application/json")
            self.assertIn(r.status_code, (200, 400), sqli)
        for t in ("sistema_pedido", "sistema_usuario", "sistema_pago"):    # ninguna tabla se borró ni se alteró
            self.assertEqual(contar_tablas()[t], self.antes[t], t)

    def test_ids_en_la_url_y_el_texto_se_guardan_como_dato_literal(self):
        sqli = "Robert'); DROP TABLE sistema_producto;--"
        r = self.client.post(reverse("api_pedido_crear"), json.dumps({"canal": "retiro", "datos": {"nombre": sqli}, "observaciones": sqli,
                             "items": [{"producto": self.prod.pk, "cantidad": 1}]}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Pedido.objects.get(pk=r.json()["id"]).pedidoretiro.nombre_retiro, sqli)   # guardado tal cual, sin ejecutarse
        self.assertTrue(Producto.objects.filter(pk=self.prod.pk).exists())

    def test_login_con_inyeccion_no_autentica(self):
        self.client.logout()
        for sqli in SQLI:
            r = self.client.post(reverse("login"), {"username": f"admin{sqli}", "password": sqli})
            self.assertEqual(r.status_code, 200)             # vuelve al formulario con error
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_el_codigo_no_arma_sql_con_texto_de_usuarios(self):
        from pathlib import Path
        for archivo in Path(__file__).parent.glob("*.py"):
            if archivo.name.startswith("test") or archivo.parent.name == "migrations":
                continue
            codigo = archivo.read_text()
            for riesgo in (".raw(", ".extra(", "RawSQL(", "cursor()", "cursor.execute"):
                self.assertNotIn(riesgo, codigo, f"{archivo.name} usa {riesgo}")


# ================================================== autorización (complementa lo anterior)
class AutorizacionTests(Base):
    def test_un_garzon_no_puede_marcar_entregado_el_pedido_de_otro(self):
        p = self.pedir("retiro", {"nombre": "Ana"})
        Pedido.objects.filter(pk=p.pk).update(estado="listo")
        otro = Usuario.objects.create_user("garzon2", password="x", rol="garzon")
        self.client.force_login(otro)
        self.assertFalse(self.client.post(reverse("api_entregar", args=[p.pk])).json()["ok"])
        self.assertEqual(Pedido.objects.get(pk=p.pk).estado, "listo")

    def test_rutas_sensibles_exigen_sesion_y_rol(self):
        for nombre in ("garzon", "cocina", "caja", "inventario", "reportes", "auditoria", "productos", "producto_crear", "insumo_crear"):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 302, nombre)       # sin sesión: al login
        self.client.force_login(self.cocina)
        for nombre in ("caja", "inventario", "reportes", "auditoria", "productos", "producto_crear"):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)       # rol insuficiente
