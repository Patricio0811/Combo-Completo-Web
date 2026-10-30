from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Insumo, Producto, Usuario


class RegistroForm(UserCreationForm):
    """Registro público. El rol NO se elige: nace como Garzón y el admin lo cambia en /admin/."""
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("username", "first_name", "last_name")

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.rol = Usuario.Rol.GARZON
        if commit:
            usuario.save()
        return usuario


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ("nombre", "precio", "activo")

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        repetido = Producto.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise ValidationError("Ya existe un producto con ese nombre.")
        return nombre

    def clean_precio(self):
        precio = self.cleaned_data["precio"]
        if precio <= 0:
            raise ValidationError("El precio debe ser mayor que cero.")
        return precio


class InsumoForm(forms.ModelForm):
    class Meta:
        model = Insumo
        fields = ("nombre", "unidad", "stock_actual", "stock_minimo")

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        repetido = Insumo.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise ValidationError("Ya existe un insumo con ese nombre.")
        return nombre

    def clean_stock_minimo(self):
        valor = self.cleaned_data["stock_minimo"]
        if valor < 0:
            raise ValidationError("El stock mínimo no puede ser negativo.")
        return valor

    def clean_stock_actual(self):
        valor = self.cleaned_data["stock_actual"]
        if valor < 0:
            raise ValidationError("El stock no puede ser negativo.")
        return valor
