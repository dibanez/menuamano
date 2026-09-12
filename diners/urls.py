from django.urls import path

from . import views

app_name = "diners"

urlpatterns = [
    path("", views.diner_list, name="list"),
    path("nuevo/", views.diner_create, name="create"),
    path("<int:pk>/", views.diner_detail, name="detail"),
    path("<int:pk>/editar/", views.diner_edit, name="edit"),
    path("<int:pk>/restricciones/", views.restrictions_save, name="restrictions_save"),
    path("<int:pk>/restricciones/dieta/", views.preset_add, name="preset_add"),
    path("<int:pk>/restricciones/<int:rid>/borrar/", views.restriction_delete, name="restriction_delete"),
    path("<int:pk>/preferencias/", views.preferences_save, name="preferences_save"),
    path("<int:pk>/preferencias/texto/", views.preference_add, name="preference_add"),
    path("<int:pk>/preferencias/<int:prid>/borrar/", views.preference_delete, name="preference_delete"),
    path("<int:pk>/asistencia/", views.attendance_save, name="attendance_save"),
    path("<int:pk>/peso/", views.weight, name="weight"),
    path("<int:pk>/peso/nuevo/", views.weight_add, name="weight_add"),
    path("<int:pk>/peso/accesos/", views.grant_add, name="grant_add"),
    path("<int:pk>/peso/accesos/<int:gid>/quitar/", views.grant_remove, name="grant_remove"),
]
