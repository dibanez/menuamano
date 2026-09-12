from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "display_name", "is_staff", "is_active", "legal_version"]
    search_fields = ["email", "display_name"]
    readonly_fields = ["terms_accepted_at", "health_consent_at", "legal_version", "last_login", "date_joined"]
    fieldsets = (
        (None, {"fields": ("email", "password", "display_name")}),
        ("Consentimientos", {"fields": ("terms_accepted_at", "health_consent_at", "legal_version")}),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
