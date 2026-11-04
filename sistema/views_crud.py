"""CRUD de Productos (con su receta de insumos) e Insumos, con vistas basadas en clases (solo administrador)."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import InsumoForm, ProductoForm, RecetaFormSet
from .models import Insumo, Producto


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
        return (Producto.objects.annotate(n_insumos=Count("recetas"))
                .prefetch_related("recetas__insumo").order_by("-activo", "nombre"))


class _ProductoGuardar(_Crud):
    """Guarda el producto y su receta (insumos del inventario que consume) en una sola transacción."""
    template_name = "sistema/producto_form.html"
    model, form_class, etiqueta = Producto, ProductoForm, "Producto"
    success_url = reverse_lazy("productos")

    def _recetas(self, data=None, instance=None):
        return RecetaFormSet(data, instance=instance if instance is not None else getattr(self, "object", None),
                             prefix="recetas")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        if "recetas" not in kw:
            ctx["recetas"] = self._recetas(self.request.POST if self.request.method == "POST" else None)
        return ctx

    def form_valid(self, form):
        recetas = self._recetas(self.request.POST, instance=form.instance)
        if not recetas.is_valid():
            return self.render_to_response(self.get_context_data(form=form, recetas=recetas))
        with transaction.atomic():
            self.object = form.save()
            recetas.instance = self.object
            recetas.save()
        messages.success(self.request, f"Producto guardado: {self.object}.")
        return redirect(self.success_url)


class ProductoCrear(_ProductoGuardar, CreateView):
    pass


class ProductoEditar(_ProductoGuardar, UpdateView):
    pass


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
