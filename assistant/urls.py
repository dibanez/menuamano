from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("", views.chat, name="chat"),
    path("enviar/", views.chat_send, name="chat_send"),
    path("proponer-menu/", views.plan_range, name="plan_range"),
    path("generar-receta/", views.generate_recipe, name="generate_recipe"),
    path("comidas/<int:pk>/alternativa/", views.replace_meal, name="replace_meal"),
    path("propuestas/<int:pk>/", views.proposal_detail, name="proposal"),
    path("propuestas/<int:pk>/aplicar/", views.proposal_apply, name="proposal_apply"),
    path("propuestas/<int:pk>/descartar/", views.proposal_discard, name="proposal_discard"),
]
