from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuenta/", include("accounts.urls")),
    path("hogar/", include("households.urls")),
    path("comensales/", include("diners.urls")),
    path("ingredientes/", include("foods.urls")),
    path("recetas/", include("recipes.urls")),
    path("calendario/", include("planning.urls")),
    path("compra/", include("shopping.urls")),
    path("asistente/", include("assistant.urls")),
    path("plan/", include("billing.urls")),
    path("recordatorios/", include("reminders.urls")),
    path("", include("core.urls")),
]
