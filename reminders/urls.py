from django.urls import path

from . import views

app_name = "reminders"

urlpatterns = [
    path("", views.settings_view, name="settings"),
    path("dispositivos/", views.subscribe, name="subscribe"),
    path("dispositivos/quitar/", views.unsubscribe, name="unsubscribe"),
    path("prueba/", views.send_test, name="test"),
]
