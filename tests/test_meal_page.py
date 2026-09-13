import re
from datetime import timedelta

from django.urls import reverse

from core.choices import MealType
from households.models import Role
from planning import services as planning

from .factories import PASSWORD, add_member, make_diner, make_recipe, make_user


def meal_page(client, user, household, monday):
    make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, make_recipe(household, "Tortilla", [("Huevo", 2, "unit")]), user)
    assert client.login(email=user.email, password=PASSWORD)
    return client.get(reverse("planning:meal", args=[meal.pk])).content.decode()


def folded(html):
    match = re.search(r'<details class="panel more">(.*?)</details>', html, re.S)
    assert match, "the secondary options must be folded"
    return match.group(1)


def test_secondary_options_are_folded_by_default(client, household, admin_user, monday):
    html = meal_page(client, admin_user, household, monday)
    more = folded(html)
    for title in ("¿Cómo es esta comida?", "¿Qué se comió?", "Mover o copiar"):
        assert title in more
    assert '<details class="panel more" open' not in html
    # Clearing the meal stays in sight, outside the fold, and still asks for a second tap.
    assert "Vaciar comida" not in more
    clear = re.search(r'<form[^>]*class="[^"]*meal-clear[^"]*"[^>]*>(.*?)</form>', html, re.S)
    assert clear and 'data-confirm="Pulsa otra vez para vaciar"' in clear.group(1)
    assert "Cambiar esta receta" in html and "Ajustar raciones" in html
    assert ">Ajustar</summary>" not in html  # ingredient changes live in one fold per recipe



def test_the_options_are_one_tap_choices(client, household, admin_user, monday):
    more = folded(meal_page(client, admin_user, household, monday))
    assert more.count('type="radio" name="mode"') == 6 and more.count('type="radio" name="outcome"') == 4
    assert 'type="radio" name="action" value="copy"' in more and 'type="radio" name="target_type"' in more
    assert 'name="locked"' not in more  # the lock has its own button at the top of the page


def test_saving_the_options_keeps_the_lock_as_it_is(client, household, admin_user, monday):
    meal_page(client, admin_user, household, monday)
    meal = planning.get_or_create_meal(household, monday, MealType.DINNER)[0]
    planning.set_locked(meal, admin_user, True)
    client.post(reverse("planning:meal_update", args=[meal.pk]), {"mode": "eat_out", "notes": "", "outcome": "pending"})
    meal.refresh_from_db()
    assert meal.mode == "eat_out" and meal.locked


def test_a_meal_is_copied_with_the_copy_choice(client, household, admin_user, monday):
    meal_page(client, admin_user, household, monday)
    meal = planning.get_or_create_meal(household, monday, MealType.DINNER)[0]
    target = monday + timedelta(days=1)
    client.post(reverse("planning:meal_move", args=[meal.pk]), {
        "action": "copy", "target_date": target.isoformat(), "target_type": MealType.DINNER,
    })
    assert meal.recipes.count() == 1  # the original stays
    copied = planning.get_or_create_meal(household, target, MealType.DINNER)[0]
    assert [r.name for r in copied.recipes.all()] == ["Tortilla"]


def test_readers_see_the_details_folded_without_forms(client, household, admin_user, monday):
    reader = make_user("reader@example.com")
    add_member(household, reader, Role.READER)
    make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    assert client.login(email=reader.email, password=PASSWORD)
    more = folded(client.get(reverse("planning:meal", args=[meal.pk])).content.decode())
    assert "Consumo:" in more and "Mover o copiar" not in more


def test_attendees_are_saved_on_change(client, household, admin_user, monday):
    html = meal_page(client, admin_user, household, monday)
    form = re.search(r'<form[^>]*class="att-form"[^>]*>', html, re.S).group(0)
    assert 'hx-trigger="change"' in form and 'hx-select="#main"' in form and 'hx-target="#main"' in form
    # The save button is only a fallback without JavaScript.
    assert re.search(r"<noscript>\s*<div[^>]*>\s*<button[^>]*>Guardar asistentes", html)


def test_add_guest_closes_the_list_of_people_and_guests_are_chips(client, household, admin_user, monday):
    make_diner(household, "Luis")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_guest(meal, admin_user, "Paco", [], "", 1)
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get(reverse("planning:meal", args=[meal.pk])).content.decode()
    people, guests, add = html.index("att-people"), html.index('class="att-guests"'), html.index("+ Añadir invitado")
    assert people < guests < add
    assert html.index('aria-label="Quitar a Paco"') < add


def test_an_htmx_attendee_change_returns_the_refreshed_page(client, household, admin_user, monday):
    ana = make_diner(household, "Ana")
    luis = make_diner(household, "Luis")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    assert client.login(email=admin_user.email, password=PASSWORD)
    response = client.post(
        reverse("planning:meal_attendees", args=[meal.pk]), {"diners": [ana.pk]}, HTTP_HX_REQUEST="true", follow=True,
    )
    assert 'id="main"' in response.content.decode()
    assert [a.diner_id for a in meal.attendees.all()] == [ana.pk]
    assert luis.pk not in [a.diner_id for a in meal.attendees.all()]
