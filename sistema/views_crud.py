"""CRUD de Productos e Insumos con vistas basadas en clases (solo administrador)."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, ProtectedError
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import InsumoForm, ProductoForm, RegistroForm
from .models import Insumo, Producto


def registro(request):
    if request.user.is_authenticated:
        return redirect("inicio")
    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        messages.success(request, "Cuenta creada. Un administrador puede cambiar tu rol.")
        return redirect("inicio")
    return render(request, "sistema/registro.html", {"form": form})


class SoloAdminMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.tiene_rol("admin")

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return render(self.request, "sistema/sin_permiso.html", status=403)


class _Crud(SoloAdminMixin):
    template_name = "sistema/crud_form.html"
    etiqueta = ""

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["etiqueta"] = self.etiqueta
        ctx["volver"] = self.success_url
        return ctx

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        messages.success(self.request, f"{self.etiqueta} guardado: {self.object}.")
        return respuesta


class _Borrar(SoloAdminMixin, DeleteView):
    template_name = "sistema/crud_borrar.html"
    etiqueta = ""

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(etiqueta=self.etiqueta, volver=self.success_url)
        return ctx

    def form_valid(self, form):
        try:
            respuesta = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, f"No se puede eliminar «{self.object}»: tiene pedidos o recetas asociados.")
            return redirect(self.success_url)
        messages.success(self.request, f"{self.etiqueta} eliminado.")
        return respuesta


# ---- Productos ----
class ProductoLista(SoloAdminMixin, ListView):
    template_name = "sistema/productos.html"
    context_object_name = "productos"

    def get_queryset(self):
        return Producto.objects.annotate(n_insumos=Count("recetas")).order_by("-activo", "nombre")


class ProductoCrear(_Crud, CreateView):
    model, form_class, etiqueta = Producto, ProductoForm, "Producto"
    success_url = reverse_lazy("productos")


class ProductoEditar(_Crud, UpdateView):
    model, form_class, etiqueta = Producto, ProductoForm, "Producto"
    success_url = reverse_lazy("productos")


class ProductoEliminar(_Borrar):
    model, etiqueta, success_url = Producto, "Producto", reverse_lazy("productos")


# ---- Insumos (la lista y el stock siguen en /inventario/) ----
class InsumoCrear(_Crud, CreateView):
    model, form_class, etiqueta = Insumo, InsumoForm, "Insumo"
    success_url = reverse_lazy("inventario")


class InsumoEditar(_Crud, UpdateView):
    model, form_class, etiqueta = Insumo, InsumoForm, "Insumo"
    success_url = reverse_lazy("inventario")


class InsumoEliminar(_Borrar):
    model, etiqueta, success_url = Insumo, "Insumo", reverse_lazy("inventario")
