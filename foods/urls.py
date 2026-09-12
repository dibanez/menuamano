from django.urls import path

from . import views

app_name = "foods"

urlpatterns = [
    path("", views.ingredient_list, name="list"),
    path("nuevo/", views.ingredient_create, name="create"),
    path("<int:pk>/editar/", views.ingredient_edit, name="edit"),
    path("<int:pk>/equivalencias/", views.equivalences, name="equivalences"),
    path("<int:pk>/equivalencias/<int:cid>/borrar/", views.equivalence_delete, name="equivalence_delete"),
    path("<int:pk>/revisar/", views.ingredient_review, name="review"),
    path("<int:pk>/revisar/borrar/", views.ingredient_review_delete, name="review_delete"),
]
