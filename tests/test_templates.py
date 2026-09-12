import re

from django.urls import reverse

from planning import services as planning

from .factories import PASSWORD, make_diner, make_recipe


def test_number_inputs_use_dot_decimals(client, household, admin_user, monday):
    make_diner(household, "Nora", portion="0.6")
    recipe = make_recipe(household, "Arroz", [("Arroz", 300, "g")])
    meal, _ = planning.get_or_create_meal(household, monday, "dinner")
    planning.add_recipe(meal, recipe, admin_user)
    assert client.login(email=admin_user.email, password=PASSWORD)

    html = client.get(reverse("planning:meal", args=[meal.pk])).content.decode()
    number_values = re.findall(r'type="number"[^>]*value="([^"]*)"', html)
    assert "0.6" in number_values
    assert not any("," in value for value in number_values)

    recipe_html = client.get(reverse("recipes:detail", args=[recipe.pk]) + "?raciones=2.5").content.decode()
    assert 'value="2.5"' in recipe_html
