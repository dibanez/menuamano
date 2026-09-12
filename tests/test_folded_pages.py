import re

from django.urls import reverse

from diners.views import _attendance_grid

from .factories import PASSWORD, make_diner, make_recipe


def folds(html):
    """Content of every «more» fold on the page, which must be closed by default."""
    assert '<details class="panel more" open' not in html
    return re.findall(r'<details class="panel more">(.*?)</details>', html, re.S)


def page(client, user, url):
    assert client.login(email=user.email, password=PASSWORD)
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


def test_recipe_page_folds_adding_history_and_archive(client, household, admin_user):
    recipe = make_recipe(household, "Tortilla", [("Huevo", 2, "unit")])
    html = page(client, admin_user, reverse("recipes:detail", args=[recipe.pk]))
    adding, more = folds(html)
    assert "Añadir al calendario" in adding
    assert "Historial" in more and "Archivar receta" in more and "Versión 1" in more


def test_week_page_folds_regeneration(client, household, admin_user):
    html = page(client, admin_user, reverse("planning:week"))
    (fill,) = folds(html)
    assert "Regenerar" in fill


def test_diner_page_folds_the_attendance_grid_with_a_summary(client, household, admin_user):
    diner = make_diner(household, "Ana")
    usual = sum(1 for row in _attendance_grid(diner, household) for _, checked in row["cells"] if checked)
    assert usual > 0
    html = page(client, admin_user, reverse("diners:detail", args=[diner.pk]))
    (attendance,) = folds(html)
    assert "Guardar asistencia" in attendance
    assert f"Suele estar en {usual} comidas a la semana" in attendance
