import re

from django import forms
from django.core.exceptions import ValidationError

from .models import Insumo, Producto, Receta

_ENTERO = re.compile(r"^\d{1,9}$")
_DECIMAL = re.compile(r"^\d{1,9}([.,]\d{1,2})?$")
_DECIMAL3 = re.compile(r"^\d{1,6}([.,]\d{1,3})?$")


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


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ("nombre", "precio", "detalle", "activo")
        labels = {"nombre": "Nombre del producto", "precio": "Precio (en pesos)",
                  "detalle": "Detalle: qué contiene el pedido",
                  "activo": "Activo (aparece en la pantalla del garzón)"}
        help_texts = {"precio": "Solo números, sin puntos ni símbolos. Ej: 3500",
                      "detalle": "Lo verá la cocina al abrir la comanda. Ej: pan de completo, vienesa, palta, tomate y mayonesa."}
        widgets = {"precio": _entrada("entero", maxlength="9", placeholder="3500"),
                   "detalle": forms.Textarea(attrs={"rows": 4, "maxlength": "500"})}

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


class RecetaForm(forms.ModelForm):
    """Una fila de la receta: qué insumo del inventario usa el producto y cuánto por cada unidad vendida."""
    cantidad_por_unidad = DecimalFlexible(max_digits=10, decimal_places=3, label="Cantidad por unidad vendida",
                                          widget=_entrada("decimal", maxlength="10", placeholder="Ej: 1 o 0,05"))

    class Meta:
        model = Receta
        fields = ("insumo", "cantidad_por_unidad")
        labels = {"insumo": "Insumo del inventario"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["insumo"].empty_label = "— Elige un insumo —"

    def clean_cantidad_por_unidad(self):
        valor = self.cleaned_data["cantidad_por_unidad"]
        if valor <= 0:
            raise ValidationError("La cantidad debe ser mayor que cero.")
        if not _DECIMAL3.match(_crudo(self, "cantidad_por_unidad")):
            raise ValidationError("Escribe solo números (decimales con coma), sin letras ni símbolos.")
        return valor


class BaseRecetaFormSet(forms.BaseInlineFormSet):
    def clean(self):
        # Primero el aviso propio (más claro que el mensaje genérico de Django sobre datos duplicados).
        vistos = set()
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            insumo = form.cleaned_data.get("insumo") if hasattr(form, "cleaned_data") else None
            if insumo is None:
                continue
            if insumo.pk in vistos:
                raise ValidationError(f"El insumo «{insumo}» está repetido: súmalo en una sola fila.")
            vistos.add(insumo.pk)
        super().clean()


RecetaFormSet = forms.inlineformset_factory(
    Producto, Receta, form=RecetaForm, formset=BaseRecetaFormSet, extra=3, can_delete=True)
