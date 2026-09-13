"""Every form that waits for the assistant says what it is doing while it waits (app.js)."""

import re

from django.urls import reverse

from .factories import PASSWORD
from .test_meal_page import meal_page


def busy_forms(html):
    return dict(re.findall(r'<form[^>]*action="([^"]+)"[^>]*data-busy="([^"]+)"', html))


def test_the_meal_page_says_it_is_looking_for_an_alternative(client, household, admin_user, monday):
    forms = busy_forms(meal_page(client, admin_user, household, monday))
    assert [text for action, text in forms.items() if "/alternativa/" in action] == ["Buscando una alternativa…"]


def test_the_week_and_the_recipe_book_say_what_they_are_doing(client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    week = busy_forms(client.get(reverse("planning:week")).content.decode())
    assert week[reverse("assistant:plan_range")] == "Preparando la propuesta…"
    recipes = busy_forms(client.get(reverse("recipes:list")).content.decode())
    assert recipes[reverse("assistant:generate_recipe")] == "Escribiendo la receta…"
    assert recipes[reverse("assistant:import_recipe")] == "Leyendo la receta…"
