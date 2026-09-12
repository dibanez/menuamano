from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("legal/", views.legal_index, name="legal"),
    path("legal/<slug:slug>/", views.legal_page, name="legal_page"),
]
