from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("entrar/", views.MenuLoginView.as_view(), name="login"),
    path("salir/", views.MenuLogoutView.as_view(), name="logout"),
    path("registro/", views.signup, name="signup"),
    path("contrasena/olvidada/", views.MenuPasswordResetView.as_view(), name="password_reset"),
    path("contrasena/enviada/", views.MenuPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("contrasena/nueva/<uidb64>/<token>/", views.MenuPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("contrasena/lista/", views.MenuPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("contrasena/cambiar/", views.MenuPasswordChangeView.as_view(), name="password_change"),
]
