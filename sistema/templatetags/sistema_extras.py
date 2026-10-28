from django import template

register = template.Library()


@register.filter
def clp(valor):
    """Pesos chilenos con punto de miles: 4000 -> 4.000 (igual que el JavaScript)."""
    try:
        return f"{int(round(float(valor))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return valor
