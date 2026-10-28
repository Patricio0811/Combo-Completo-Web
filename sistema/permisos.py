from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render


def rol_requerido(*roles, api=False):
    """Restringe la vista por rol. El administrador accede a todo."""
    def deco(vista):
        @wraps(vista)
        @login_required
        def interna(request, *a, **kw):
            if not request.user.tiene_rol(*roles):
                if api:
                    return JsonResponse({"error": "Sin permiso"}, status=403)
                return render(request, "sistema/sin_permiso.html", status=403)
            return vista(request, *a, **kw)
        return interna
    return deco
