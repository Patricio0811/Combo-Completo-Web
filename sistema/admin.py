from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models


@admin.register(models.Usuario)
class UsuarioAdmin(UserAdmin):
    """CU08: gestionar usuarios y roles."""
    list_display = ("username", "first_name", "last_name", "rol", "is_active")
    list_filter = ("rol", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Rol en el local", {"fields": ("rol",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Rol en el local", {"fields": ("rol",)}),)


class RecetaInline(admin.TabularInline):
    model = models.Receta
    extra = 1


@admin.register(models.Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "precio", "activo")
    inlines = [RecetaInline]


admin.site.register(models.Insumo)
