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

`cargar_datos` crea cuatro usuarios cuya clave es igual al nombre:

| Usuario | Clave | Rol |
|---|---|---|
| `garzon` | `garzon` | Garzón |
| `cocina` | `cocina` | Personal de cocina |
| `cajero` | `cajero` | Cajero |
| `admin` | `admin` | Administrador |

También puedes crear una cuenta nueva en `/registro/`: nace con rol Garzón y el administrador puede cambiarlo en `/admin/`.
**Cambia estas claves antes de la demo o de usar el sistema en el local.**

## Pantallas por rol

| Rol | Pantalla | Qué hace |
|---|---|---|
| Garzón | `/garzon/` | Pedido en una pantalla (canal → datos → productos), aviso de "pedido listo" |
| Cocina | `/cocina/` | Comandas por hora de llegada, se actualiza cada 2 s |
| Cajero | `/caja/` | Cobro por medio de pago y cierre de caja |
| Administrador | `/productos/` | CRUD de productos (crear, editar, eliminar) |
| Administrador | `/inventario/` | Stock, alertas, entradas, ajustes y CRUD de insumos |
| Administrador | `/reportes/` | Ventas por período, canal, día y medio de pago; ticket promedio; más vendidos |
| Administrador | `/auditoria/` | Registro de anulaciones, ajustes y diferencias de caja |
| Administrador | `/admin/` | Usuarios y roles |

## Guía rápida para probar (demo)

1. Entra como `garzon`, crea un pedido (por ejemplo Local, mesa 4, con 2 productos).
2. Entra como `cocina`, pasa la comanda a "En preparación" y luego a "Lista".
3. Vuelve a `garzon`: aparece el aviso de pedido listo; márcalo como entregado.
4. Entra como `cajero`, registra el pago del pedido y haz el cierre de caja.
5. Entra como `admin`:
   - `/productos/`: crea, edita y elimina un producto.
   - `/inventario/`: revisa que el stock bajó; registra una entrada o un ajuste.
   - `/reportes/`: revisa las ventas del día.
   - `/auditoria/`: revisa los registros.
6. Prueba que un garzón no puede entrar a `/reportes/` (debe mostrar "sin permiso").

## Pruebas automáticas

```powershell
python manage.py test
```
Son 20 pruebas. Para correrlas contra PostgreSQL, deja `DATABASE_URL` definida en `.env` (el usuario de la base necesita permiso `CREATEDB`; en el servidor local `postgres` ya lo tiene).

## Si algo falla

| Problema | Solución |
|---|---|
| `ModuleNotFoundError` | Activa el entorno virtual y ejecuta `pip install -r requirements.txt` |
| `password authentication failed` | Revisa usuario y clave en `DATABASE_URL` |
| `database "combo" does not exist` | Crea la base con `CREATE DATABASE combo;` |
| `connection refused` | PostgreSQL no está encendido; inicia el servicio |
| Error por usuario o tabla al migrar una base antigua | Borra `db.sqlite3` (o recrea la base): el proyecto usa un modelo de usuario propio (`sistema.Usuario`) |
| Cambió tu `SECRET_KEY` y no se leen teléfonos | Define `FIELD_ENCRYPTION_KEY` fija; sin ella la clave de cifrado depende de `SECRET_KEY` |

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
  views_crud.py       registro y CRUD de productos e insumos (vistas basadas en clases)
  forms.py            formularios y validaciones
  permisos.py         control de acceso por rol
  templates/ static/  front end
```