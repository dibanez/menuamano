from django.urls import path

from . import views

app_name = "shopping"

urlpatterns = [
    path("", views.current, name="current"),
    path("listas/", views.index, name="index"),
    path("listas/nueva/", views.create, name="create"),
    path("listas/<int:pk>/", views.detail, name="detail"),
    path("listas/<int:pk>/recalcular/", views.recalculate, name="recalculate"),
    path("listas/<int:pk>/borrar/", views.delete, name="delete"),
    path("listas/<int:pk>/articulos/", views.manual_add, name="manual_add"),
    path("articulos/<int:pk>/marcar/", views.item_toggle, name="item_toggle"),
    path("articulos/<int:pk>/comprado/", views.item_purchased, name="item_purchased"),
    path("articulos/<int:pk>/borrar/", views.item_delete, name="item_delete"),
]
