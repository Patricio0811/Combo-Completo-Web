from django.contrib.auth import views as auth
from django.urls import path

from . import views

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
]
