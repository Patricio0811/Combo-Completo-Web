from django.contrib.auth import views as auth
from django.urls import path

from . import views, views_crud as crud

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("ingresar/", auth.LoginView.as_view(template_name="sistema/login.html"), name="login"),
    path("salir/", auth.LogoutView.as_view(), name="logout"),
    path("garzon/", views.garzon, name="garzon"),
    path("api/pedidos/", views.api_pedido_crear, name="api_pedido_crear"),
    path("api/pedidos/listos/", views.api_listos, name="api_listos"),
    path("api/pedidos/<int:pk>/entregar/", views.api_entregar, name="api_entregar"),
    path("cocina/", views.cocina, name="cocina"),
    path("api/comandas/", views.api_comandas, name="api_comandas"),
    path("api/comandas/<int:pk>/estado/", views.api_comanda_estado, name="api_comanda_estado"),
    path("inventario/", views.inventario, name="inventario"),
    path("caja/", views.caja, name="caja"),
    path("reportes/", views.reportes, name="reportes"),
    path("auditoria/", views.auditoria, name="auditoria"),
    path("registro/", crud.registro, name="registro"),
    path("productos/", crud.ProductoLista.as_view(), name="productos"),
    path("productos/nuevo/", crud.ProductoCrear.as_view(), name="producto_crear"),
    path("productos/<int:pk>/editar/", crud.ProductoEditar.as_view(), name="producto_editar"),
    path("productos/<int:pk>/eliminar/", crud.ProductoEliminar.as_view(), name="producto_eliminar"),
    path("insumos/nuevo/", crud.InsumoCrear.as_view(), name="insumo_crear"),
    path("insumos/<int:pk>/editar/", crud.InsumoEditar.as_view(), name="insumo_editar"),
    path("insumos/<int:pk>/eliminar/", crud.InsumoEliminar.as_view(), name="insumo_eliminar"),
]
