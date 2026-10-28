# El Combo Completo – sistema de inventario (front end + lógica)

## Cómo ejecutarlo
```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py cargar_datos      # usuarios, productos, insumos y recetas de ejemplo
python manage.py runserver
```
Abre http://127.0.0.1:8000. Usuarios de prueba (clave = nombre): `garzon`, `cocina`, `cajero`, `admin`.
Si ya habías ejecutado `migrate` antes, borra `db.sqlite3`: el proyecto usa un modelo de usuario propio (`sistema.Usuario`).
Pruebas: `python manage.py test`.

## Pantallas por rol
| Rol | Pantalla | Qué hace |
|---|---|---|
| Garzón | /garzon/ | Pedido en una pantalla (canal → datos → productos), aviso de "pedido listo" |
| Cocina | /cocina/ | Comandas por hora de llegada, se actualiza cada 2 s |
| Cajero | /caja/ | Cobro por medio de pago y cierre de caja |
| Administrador | /inventario/, /reportes/, /auditoria/, /admin/ | Stock y alertas, ventas por período y canal, auditoría, usuarios y roles |

## Antes de usar en el local
Cambia SECRET_KEY, pon DEBUG = False, define ALLOWED_HOSTS y cambia las claves de prueba.
