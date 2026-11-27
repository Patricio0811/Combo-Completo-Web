"""Formularios del CRUD de Agregados (salsas, más papas, etc.) y de su receta de insumos.
Van en un archivo aparte para no tocar forms.py; usan las mismas reglas de validación numérica."""
import re
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory

from .models import Agregado, RecetaAgregado
from .services import ErrorNegocio, leer_entero

_CANTIDAD = re.compile(r"^\d{1,6}([.,]\d{1,3})?$")    # la receta guarda hasta 3 decimales (0,050)


class AgregadoForm(forms.ModelForm):
    precio = forms.CharField(
        label="Precio ($)", max_length=9,
        widget=forms.TextInput(attrs={"data-tipo": "entero", "inputmode": "numeric", "autocomplete": "off"}))

    class Meta:
        model = Agregado
        fields = ["nombre", "precio", "activo"]

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        if not nombre:
            raise forms.ValidationError("Escribe el nombre del agregado.")
        return nombre

    def clean_precio(self):
        try:
            return leer_entero(self.cleaned_data["precio"], "Precio")
        except ErrorNegocio as e:
            raise forms.ValidationError(str(e))


class RecetaAgregadoForm(forms.ModelForm):
    cantidad_por_unidad = forms.CharField(
        label="Cantidad por unidad", max_length=10,
        widget=forms.TextInput(attrs={"data-tipo": "decimal", "inputmode": "decimal", "autocomplete": "off"}))

    class Meta:
        model = RecetaAgregado
        fields = ["insumo", "cantidad_por_unidad"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:        # muestra 0.05 y no 0.050
            self.initial["cantidad_por_unidad"] = format(self.instance.cantidad_por_unidad.normalize(), "f")

    def clean_cantidad_por_unidad(self):
        texto = str(self.cleaned_data["cantidad_por_unidad"]).strip()
        if not _CANTIDAD.match(texto):
            raise forms.ValidationError("Cantidad: escribe solo números (puedes usar coma, hasta 3 decimales).")
        cant = Decimal(texto.replace(",", "."))
        if cant <= 0:
            raise forms.ValidationError("La cantidad debe ser mayor que cero.")
        return cant


RecetaAgregadoFormSet = inlineformset_factory(
    Agregado, RecetaAgregado, form=RecetaAgregadoForm, extra=2, can_delete=True)
