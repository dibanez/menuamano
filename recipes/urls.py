from django.urls import path

from . import views

app_name = "recipes"

urlpatterns = [
    path("", views.recipe_list, name="list"),
    path("nueva/", views.recipe_create, name="create"),
    path("<int:pk>/", views.recipe_detail, name="detail"),
    path("<int:pk>/editar/", views.recipe_edit, name="edit"),
    path("<int:pk>/favorita/", views.favorite_toggle, name="favorite"),
    path("<int:pk>/archivar/", views.archive_toggle, name="archive"),
    path("<int:pk>/revisada/", views.mark_reviewed, name="reviewed"),
]
