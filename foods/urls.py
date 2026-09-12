from django.urls import path

from . import views

app_name = "foods"

urlpatterns = [
    path("", views.ingredient_list, name="list"),
    path("nuevo/", views.ingredient_create, name="create"),
    path("<int:pk>/editar/", views.ingredient_edit, name="edit"),
]
