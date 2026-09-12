from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("entrar/", views.MenuLoginView.as_view(), name="login"),
    path("salir/", views.MenuLogoutView.as_view(), name="logout"),
    path("registro/", views.signup, name="signup"),
]
