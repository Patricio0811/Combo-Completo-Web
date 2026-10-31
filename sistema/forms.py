import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Insumo, Producto, Usuario

_ENTERO = re.compile(r"^\d{1,9}$")
_DECIMAL = re.compile(r"^\d{1,9}([.,]\d{1,2})?$")


def _crudo(form, campo):
    """Texto tal como lo escribió la persona (Django ya lo convirtió a Decimal; aquí se revisa el original)."""
    return str(form.data.get(form.add_prefix(campo), "")).strip()


class DecimalFlexible(forms.DecimalField):
    """Acepta coma o punto como separador decimal."""
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        return super().to_python(value)


def _entrada(tipo, **extra):
    attrs = {"data-tipo": tipo, "inputmode": "numeric" if tipo == "entero" else "decimal", "autocomplete": "off"}
    attrs.update(extra)
    return forms.TextInput(attrs=attrs)


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
        labels = {"nombre": "Nombre del producto", "precio": "Precio (en pesos)",
                  "activo": "Activo (aparece en la pantalla del garzón)"}
        help_texts = {"precio": "Solo números, sin puntos ni símbolos. Ej: 3500"}
        widgets = {"precio": _entrada("entero", maxlength="9", placeholder="3500")}

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
        if not _ENTERO.match(_crudo(self, "precio")):
            raise ValidationError("Escribe solo números enteros, sin letras, puntos ni símbolos.")
        return precio


class InsumoForm(forms.ModelForm):
    stock_actual = DecimalFlexible(max_digits=12, decimal_places=2, label="Stock actual",
                                   help_text="Solo números; para decimales usa coma. Ej: 2,5",
                                   widget=_entrada("decimal", maxlength="12"))
    stock_minimo = DecimalFlexible(max_digits=12, decimal_places=2, label="Stock mínimo",
                                   help_text="Bajo este valor el sistema crea una alerta.",
                                   widget=_entrada("decimal", maxlength="12"))

    class Meta:
        model = Insumo
        fields = ("nombre", "unidad", "stock_actual", "stock_minimo")
        labels = {"nombre": "Nombre del insumo", "unidad": "Unidad de medida"}
        help_texts = {"unidad": "Ej: un, kg, litros"}

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
        if not _DECIMAL.match(_crudo(self, "stock_minimo")):
            raise ValidationError("Escribe solo números, sin letras ni símbolos (decimales con coma).")
        return valor

    def clean_stock_actual(self):
        valor = self.cleaned_data["stock_actual"]
        if valor < 0:
            raise ValidationError("El stock no puede ser negativo.")
        if not _DECIMAL.match(_crudo(self, "stock_actual")):
            raise ValidationError("Escribe solo números, sin letras ni símbolos (decimales con coma).")
        return valor
