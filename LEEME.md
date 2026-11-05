# El Combo Completo – sistema de inventario (Django)

Aplicación web para el local: pedidos por canal (Local, Retiro, Domicilio), cocina, caja, inventario, reportes y auditoría.

## Requisitos
- Python 3.12 o superior
- Git
- PostgreSQL 14 o superior (opcional: sin él, el proyecto usa SQLite)

## Ejecutar en local (rápido, con SQLite)

```powershell
python -m venv venv
venv\Scripts\activate            # en Linux/Mac: source venv/bin/activate
python -m pip install -r requirements.txt
copy .env.example .env           # en Linux/Mac: cp .env.example .env
python manage.py migrate
python manage.py cargar_datos    # usuarios, productos, insumos y recetas de ejemplo
python manage.py runserver
```

Abre http://127.0.0.1:8000

## Ejecutar con PostgreSQL

1. Crea la base vacía (en `psql` o pgAdmin):
   ```sql
   CREATE DATABASE combo;
   ```
2. En el archivo `.env` descomenta y completa la línea:
   ```
   DATABASE_URL=postgres://postgres:TU_CLAVE@localhost:5432/combo
   ```
3. Crea las tablas y los datos de ejemplo:
   ```powershell
   python manage.py migrate
   python manage.py cargar_datos
   python manage.py runserver
   ```

Si `DATABASE_URL` está vacía o no existe, se usa SQLite (`db.sqlite3`).
Los datos de una base no se pasan a la otra: al cambiar de SQLite a PostgreSQL empiezas con la base vacía.

## Variables de entorno (archivo `.env`)

| Variable | Para qué sirve | Local | Producción |
|---|---|---|---|
| `DJANGO_DEBUG` | Modo desarrollo | `True` | `False` |
| `DJANGO_SECRET_KEY` | Clave secreta de Django | opcional | **obligatoria** |
| `DJANGO_ALLOWED_HOSTS` | Dominios permitidos | `localhost,127.0.0.1` | dominio de la app |
| `DATABASE_URL` | Conexión a PostgreSQL | vacía = SQLite | **obligatoria** |
| `FIELD_ENCRYPTION_KEY` | Clave que cifra teléfono y dirección de clientes | opcional | **obligatoria, no cambiarla después** |
| `CSRF_TRUSTED_ORIGINS` | URL pública con https | vacía | `https://tu-app.onrender.com` |

Para generar una `FIELD_ENCRYPTION_KEY`:
```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
El archivo `.env` no se sube a git (está en `.gitignore`).

## Usuarios de prueba

`cargar_datos` crea dos usuarios cuya clave es igual al nombre:

| Usuario | Clave | Rol |
|---|---|---|
| `cocina` | `cocina` | Personal de cocina |
| `admin` | `admin` | Administrador |

No existe el registro público de cuentas: solo el administrador crea usuarios y roles, en `/admin/` (Usuarios y roles). El administrador también puede tomar pedidos y cobrar.
**Cambia estas claves antes de la demo o de usar el sistema en el local.**

## Pantallas por rol

| Rol | Pantalla | Qué hace |
|---|---|---|
| Garzón (o administrador) | `/garzon/` | Pedido en una pantalla: canal obligatorio (Retiro o Domicilio) → datos → productos. Retiro pide el nombre de quien retira; Domicilio pide nombre, teléfono, dirección y costo de envío. Aviso de "pedido listo" |
| Cocina | `/cocina/` | Comandas por hora de llegada, se actualiza cada 2 s. «Ver detalle» amplía la comanda y muestra qué contiene cada producto y los insumos que usa |
| Cajero | `/caja/` | Cobro por medio de pago y cierre de caja |
| Administrador | `/productos/` | CRUD de productos: nombre, precio, detalle (qué contiene) y receta (insumos del inventario que se descuentan al vender) |
| Administrador | `/inventario/` | Stock, alertas, entradas, ajustes y CRUD de insumos |
| Administrador | `/reportes/` | Ventas por período, canal, día y medio de pago; ticket promedio; más vendidos |
| Administrador | `/auditoria/` | Registro de anulaciones, ajustes y diferencias de caja |
| Administrador | `/admin/` | Usuarios y roles |

## Guía rápida para probar (demo)

1. Entra como `admin` (o como garzón, si lo creas en `/admin/`), crea un pedido: elige Retiro (nombre de quien retira) o Domicilio (datos del cliente y costo de envío) y agrega 2 productos.
2. Entra como `cocina`, abre «Ver detalle» en la comanda y pásala a "En preparación" y luego a "Lista".
3. Vuelve a la pantalla de pedidos: aparece el aviso de pedido listo; márcalo como entregado.
4. Entra a `/caja/` (como `admin` o como cajero), registra el pago del pedido y haz el cierre de caja.
5. Entra como `admin`:
   - `/productos/`: crea un producto con su detalle y sus insumos; edítalo o elimínalo.
   - `/inventario/`: revisa que el stock bajó; registra una entrada o un ajuste.
   - `/reportes/`: revisa las ventas del día.
   - `/auditoria/`: revisa los registros.
6. Prueba que la cocina no puede entrar a `/reportes/` (debe mostrar "sin permiso").

## Pruebas automáticas

```powershell
python manage.py test
```
Son 71 pruebas. Para correrlas contra PostgreSQL, deja `DATABASE_URL` definida en `.env` (el usuario de la base necesita permiso `CREATEDB`; en el servidor local `postgres` ya lo tiene).

## Estilo y validaciones del front end

- **Botones:** un solo estilo en todo el sistema. Rojo lleno = acción principal, borde oscuro = acción normal, borde rojo = acción riesgosa (anular, eliminar, ajustar stock). Los colores y medidas están en `static/sistema/app.css`.
- **Campos numéricos:** en montos de pago, cierre de caja, precios y cantidades de inventario y de recetas solo se aceptan números. `static/sistema/validacion.js` borra letras y símbolos mientras se escribe (se activa con `data-tipo="entero"`, `"decimal"` o `"telefono"` en el `<input>`).
- **Validación en el servidor:** `services.leer_entero()` / `leer_decimal()` y `forms.py` repiten la revisión y rechazan letras, símbolos, negativos, `NaN`, notación científica (`1e3`) y números de más de 9 dígitos. Los montos son enteros en pesos (`3500`, no `3.500`); las cantidades admiten coma decimal.

## Seguridad (inyección SQL, XSS y CSRF)

`sistema/test_seguridad.py` ataca la aplicación con payloads reales y comprueba que no tengan efecto:

- **CSRF:** todos los POST (formularios y APIs de JavaScript) rechazan la petición sin token (403) y no cambian datos; ninguna acción que modifica datos responde a GET; el login y el logout también exigen token.
- **XSS:** datos hostiles (`<script>`, `"><img onerror>`, `</script>` dentro del JSON, etc.) guardados en productos, insumos, pedidos, observaciones, auditoría y nombres de usuario salen siempre escapados en todas las pantallas. Un analizador de HTML verifica que el payload no se vuelva activo. El JavaScript inserta datos solo con `textContent`.
- **Inyección SQL:** payloads clásicos en parámetros GET, campos POST, ids y el cuerpo JSON no filtran datos, no borran tablas y no producen errores 500. El código no usa SQL crudo (`.raw`, `.extra`, `cursor`); una prueba lo vigila.
- **Otros:** cabecera anti-clickjacking, `nosniff`, redirección abierta en el login y que un garzón no pueda entregar pedidos de otro.

Para probarlo: `python manage.py test sistema.test_seguridad`. Antes de publicar: `DJANGO_DEBUG=False python manage.py check --deploy`.

## Si algo falla

| Problema | Solución |
|---|---|
| `ModuleNotFoundError` | Activa el entorno virtual y ejecuta `pip install -r requirements.txt` |
| `password authentication failed` | Revisa usuario y clave en `DATABASE_URL` |
| `database "combo" does not exist` | Crea la base con `CREATE DATABASE combo;` |
| `connection refused` | PostgreSQL no está encendido; inicia el servicio |
| Error por usuario o tabla al migrar una base antigua | Borra `db.sqlite3` (o recrea la base): el proyecto usa un modelo de usuario propio (`sistema.Usuario`) |
| Teléfono o dirección de un cliente aparece como «[dato cifrado con otra clave…]» (antes: error `InvalidToken`) | Esos datos se cifraron con otra clave (por ejemplo, cambió `SECRET_KEY`). El sistema ya no se cae. Para recuperarlos, define `DJANGO_SECRET_KEY_ANTERIORES` con la clave antigua y ejecuta `python manage.py reencriptar_clientes`. Si eran datos de prueba, bórralos en `/admin/`. Para que no vuelva a pasar, define una `FIELD_ENCRYPTION_KEY` fija |

## Despliegue en la nube (Render)

1. Crea una base **PostgreSQL** en Render y copia su *Internal Database URL*.
2. Crea un **Web Service** conectado al repositorio de GitHub:
   - Build command: `./build.sh`
   - Start command: `gunicorn sistema_inventario.wsgi`
3. Define las variables de entorno: `DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` (el dominio de Render), `DATABASE_URL`, `FIELD_ENCRYPTION_KEY` y `CSRF_TRUSTED_ORIGINS` (`https://...onrender.com`).
4. Con la primera publicación, abre la Shell del servicio y ejecuta `python manage.py cargar_datos` para tener usuarios y productos de ejemplo. Luego cambia las claves.

## Estructura del proyecto

```
sistema_inventario/   configuración (settings, urls, wsgi)
sistema/
  models.py           modelos (Usuario, Producto, Insumo, Pedido y subtipos, Pago, etc.)
  services.py         reglas de negocio (crear pedido, descontar stock, pagos, cierre de caja)
  views.py            pantallas por rol, API de pedidos/comandas, reportes
  views_crud.py       CRUD de productos (con receta) e insumos (vistas basadas en clases)
  forms.py            formularios y validaciones
  permisos.py         control de acceso por rol
  templates/ static/  front end
```