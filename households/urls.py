from django.urls import path

from . import views

app_name = "households"

urlpatterns = [
    path("nuevo/", views.onboarding, name="onboarding"),
    path("cambiar/", views.switch, name="switch"),
    path("configuracion/", views.settings_view, name="settings"),
    path("miembros/nuevo/", views.add_member, name="add_member"),
    path("miembros/<int:pk>/rol/", views.change_role, name="change_role"),
    path("miembros/<int:pk>/quitar/", views.remove_member, name="remove_member"),
]
