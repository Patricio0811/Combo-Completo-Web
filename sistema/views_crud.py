"""CRUD de Productos (con su receta de insumos) e Insumos, con vistas basadas en clases (solo administrador)."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import InsumoForm, ProductoForm, RecetaFormSet
from .forms_agregados import AgregadoForm, RecetaAgregadoFormSet
from .models import Agregado, Insumo, Producto
from .services import _fmt, auditar


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
        nombre = str(self.object)
        try:
            respuesta = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, f"No se puede eliminar «{nombre}»: tiene pedidos o recetas asociados.")
            return redirect(self.success_url)
        auditar(self.request.user, f"{self.etiqueta.lower()}_eliminado", nombre=nombre)
        messages.success(self.request, f"{self.etiqueta} eliminado.")
        return respuesta


# ---- Productos ----
class ProductoLista(SoloAdminMixin, ListView):
    template_name = "sistema/productos.html"
    context_object_name = "productos"

    def get_queryset(self):
        return (Producto.objects.annotate(n_insumos=Count("recetas"))
                .prefetch_related("recetas__insumo").order_by("-activo", "nombre"))

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        # Apartado «Agregados» dentro de la ventana de productos (se dibuja con sistema/_agregados.html)
        ctx["agregados"] = (Agregado.objects.annotate(n_insumos=Count("recetas"))
                            .prefetch_related("recetas__insumo").order_by("-activo", "nombre"))
        return ctx


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
        es_nuevo = form.instance.pk is None
        precio_antes = None if es_nuevo else Producto.objects.filter(pk=form.instance.pk).values_list("precio", flat=True).first()
        with transaction.atomic():
            self.object = form.save()
            recetas.instance = self.object
            recetas.save()
            if es_nuevo:
                auditar(self.request.user, "producto_creado", producto=self.object.nombre, precio=str(self.object.precio))
            elif precio_antes is not None and precio_antes != self.object.precio:
                auditar(self.request.user, "cambio_precio", producto=self.object.nombre,
                        antes=str(precio_antes), despues=str(self.object.precio))
        messages.success(self.request, f"Producto guardado: {self.object}.")
        return redirect(self.success_url)


class ProductoCrear(_ProductoGuardar, CreateView):
    pass


class ProductoEditar(_ProductoGuardar, UpdateView):
    pass


class ProductoEliminar(_Borrar):
    model, etiqueta, success_url = Producto, "Producto", reverse_lazy("productos")


# ---- Agregados (salsas, más papas, etc.): precio + receta de insumos, igual que un producto ----
class _AgregadoGuardar(_Crud):
    template_name = "sistema/agregado_form.html"
    model, form_class, etiqueta = Agregado, AgregadoForm, "Agregado"
    success_url = reverse_lazy("productos")

    def _recetas(self, data=None, instance=None):
        return RecetaAgregadoFormSet(data, instance=instance if instance is not None else getattr(self, "object", None),
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
        es_nuevo = form.instance.pk is None
        precio_antes = None if es_nuevo else Agregado.objects.filter(pk=form.instance.pk).values_list("precio", flat=True).first()
        with transaction.atomic():
            self.object = form.save()
            recetas.instance = self.object
            recetas.save()
            if es_nuevo:
                auditar(self.request.user, "agregado_creado", agregado=self.object.nombre, precio=str(self.object.precio))
            elif precio_antes is not None and precio_antes != self.object.precio:
                auditar(self.request.user, "cambio_precio_agregado", agregado=self.object.nombre,
                        antes=str(precio_antes), despues=str(self.object.precio))
        messages.success(self.request, f"Agregado guardado: {self.object}.")
        return redirect(self.success_url)


class AgregadoCrear(_AgregadoGuardar, CreateView):
    pass


class AgregadoEditar(_AgregadoGuardar, UpdateView):
    pass


class AgregadoEliminar(_Borrar):
    model, etiqueta, success_url = Agregado, "Agregado", reverse_lazy("productos")


# ---- Insumos (la lista y el stock siguen en /inventario/) ----
class InsumoCrear(_Crud, CreateView):
    model, form_class, etiqueta = Insumo, InsumoForm, "Insumo"
    success_url = reverse_lazy("inventario")


class InsumoEditar(_Crud, UpdateView):
    model, form_class, etiqueta = Insumo, InsumoForm, "Insumo"
    success_url = reverse_lazy("inventario")

    def form_valid(self, form):
        antes = Insumo.objects.filter(pk=form.instance.pk).values_list("stock_actual", flat=True).first()
        respuesta = super().form_valid(form)
        if antes is not None and antes != self.object.stock_actual:   # cambio de stock hecho a mano: queda registrado
            auditar(self.request.user, "ajuste_stock", insumo=self.object.nombre, antes=_fmt(antes),
                    despues=_fmt(self.object.stock_actual), motivo="edición del insumo")
        return respuesta


class InsumoEliminar(_Borrar):
    model, etiqueta, success_url = Insumo, "Insumo", reverse_lazy("inventario")
