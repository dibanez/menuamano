from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.plan, name="plan"),
    path("suscribirse/", views.checkout, name="checkout"),
    path("gestionar/", views.portal, name="portal"),
    path("gracias/", views.success, name="success"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
