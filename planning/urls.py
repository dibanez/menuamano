from django.urls import path

from . import views

app_name = "planning"

urlpatterns = [
    path("", views.week, name="week"),
    path("mes/", views.month, name="month"),
    path("dia/<str:day>/", views.day, name="day"),
    path("suscribirse/", views.calendar_subscribe, name="subscribe"),
    path("suscribirse/quitar/", views.calendar_unsubscribe, name="unsubscribe"),
    path("ics/<str:token>.ics", views.calendar_feed, name="feed"),
    path("hueco/<str:day>/<str:meal_type>/", views.slot, name="slot"),
    path("anadir-receta/", views.add_recipe_to_slot, name="add_recipe_to_slot"),
    path("regenerar/", views.regenerate, name="regenerate"),
    path("comidas/<int:pk>/", views.meal_detail, name="meal"),
    path("comidas/<int:pk>/datos/", views.meal_update, name="meal_update"),
    path("comidas/<int:pk>/proteger/", views.meal_lock, name="meal_lock"),
    path("comidas/<int:pk>/sobras/", views.meal_leftovers, name="meal_leftovers"),
    path("comidas/<int:pk>/sobras/quitar/", views.meal_leftovers_clear, name="meal_leftovers_clear"),
    path("comidas/<int:pk>/asistentes/", views.meal_attendees, name="meal_attendees"),
    path("comidas/<int:pk>/invitados/", views.meal_add_guest, name="meal_add_guest"),
    path("comidas/<int:pk>/asistentes/<int:aid>/quitar/", views.meal_remove_attendee, name="meal_remove_attendee"),
    path("comidas/<int:pk>/recetas/", views.meal_add_recipe, name="meal_add_recipe"),
    path("comidas/<int:pk>/recetas/<int:mrid>/quitar/", views.meal_remove_recipe, name="meal_remove_recipe"),
    path("comidas/<int:pk>/recetas/<int:mrid>/raciones/", views.meal_recipe_servings, name="meal_recipe_servings"),
    path("comidas/<int:pk>/recetas/<int:mrid>/para-quien/", views.meal_recipe_eaters, name="meal_recipe_eaters"),
    path("comidas/<int:pk>/recetas/<int:mrid>/actualizar/", views.meal_recipe_refresh, name="meal_recipe_refresh"),
    path("comidas/<int:pk>/lineas/<int:lid>/cantidad/", views.line_quantity, name="line_quantity"),
    path("comidas/<int:pk>/lineas/<int:lid>/sustituir/", views.line_substitute, name="line_substitute"),
    path("comidas/<int:pk>/mover/", views.meal_move, name="meal_move"),
    path("comidas/<int:pk>/vaciar/", views.meal_delete, name="meal_delete"),
    path("reglas/", views.rules, name="rules"),
    path("reglas/nueva/", views.rule_add, name="rule_add"),
    path("reglas/<int:pk>/borrar/", views.rule_delete, name="rule_delete"),
    path("excepciones/nueva/", views.exception_add, name="exception_add"),
    path("excepciones/<int:pk>/borrar/", views.exception_delete, name="exception_delete"),
]
