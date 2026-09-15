"""The diner configurator: a few questions that become the diner's restrictions."""

from decimal import Decimal

import pytest
from django.urls import reverse

from assistant.context import build_context
from core.choices import MealType
from diners import services
from diners.forms import DinerWizardForm
from diners.models import Diner, DinerRestriction
from foods import openfoodfacts
from foods.models import Trait
from households.models import Role
from planning import services as planning
from planning.models import Meal, SafetyStatus

from .factories import PASSWORD, add_member, ingredient, make_diner, make_recipe, make_user


@pytest.fixture
def logged(client, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    return client


def answers(**extra):
    """The configurator's form as the browser sends it."""
    data = {"alias": "Leo", "birth_date": "", "portion": "1.00", "diet": "omnivore", "diabetes": "no"}
    data.update(extra)
    return data


def profile(**extra):
    """The configurator's cleaned answers, for the service."""
    data = {
        "alias": "Leo", "birth_date": None, "portion": Decimal("1.00"), "diet": "omnivore", "extras": [],
        "allergies": [], "intolerances": [], "ingredients": [], "diabetes": "no",
    }
    data.update(extra)
    return data


def restrictions(diner):
    return {(r.trait or r.ingredient.name, r.kind) for r in diner.restrictions.select_related("ingredient")}


def test_a_new_diner_is_configured_in_one_go(logged, household):
    response = logged.post(reverse("diners:create"), answers(
        portion="0.75", diet="vegetarian", extras=["no_alcohol"], allergies=["peanut"], intolerances=["lactose"],
        ingredients=[ingredient("Kiwi").pk], diabetes="yes",
    ))
    leo = Diner.objects.get(household=household, alias="Leo")
    assert response.url == reverse("diners:detail", args=[leo.pk])
    assert leo.portion_factor == Decimal("0.75")
    assert restrictions(leo) == {
        ("meat", "diet"), ("fish", "diet"), ("crustaceans", "diet"), ("molluscs", "diet"), ("alcohol", "diet"),
        ("peanut", "allergy"), ("lactose", "intolerance"), ("Kiwi", "other"), ("added_sugar", "diabetes"),
    }


def test_the_configurator_opens_with_what_the_diner_has(logged, household):
    leo = make_diner(household, "Leo")
    services.save_profile(leo, profile(
        diet="vegan", extras=["no_alcohol"], allergies=["sesame"], intolerances=["gluten"], diabetes="yes",
    ))
    assert services.wizard_initial(leo) == {
        "alias": "Leo", "birth_date": None, "portion": "1.00", "diet": "vegan", "extras": ["no_alcohol"],
        "allergies": ["sesame"], "intolerances": ["gluten"], "ingredients": [], "diabetes": "yes",
        "linked_user": None,
    }
    before = sorted(leo.restrictions.values_list("pk", flat=True))
    services.save_profile(leo, profile(**{k: v for k, v in services.wizard_initial(leo).items() if k != "portion"}))
    assert sorted(leo.restrictions.values_list("pk", flat=True)) == before  # saving the same answers changes nothing
    page = logged.get(reverse("diners:setup", args=[leo.pk])).content.decode()
    assert "¿Tiene diabetes?" in page and "Guardar cambios" in page


def test_answers_replace_the_old_restrictions_and_keep_their_notes(logged, household):
    leo = make_diner(household, "Leo")
    egg = DinerRestriction.objects.create(diner=leo, kind="allergy", trait=Trait.EGG, label="anafilaxia")
    DinerRestriction.objects.create(diner=leo, kind="allergy", trait=Trait.SOY)
    logged.post(reverse("diners:setup", args=[leo.pk]), answers(allergies=["egg"], intolerances=["gluten"]))
    assert restrictions(leo) == {("egg", "allergy"), ("gluten", "intolerance")}
    assert DinerRestriction.objects.get(pk=egg.pk).label == "anafilaxia"


def test_gluten_marked_as_allergy_and_intolerance_is_an_allergy(household):
    leo = make_diner(household, "Leo")
    services.save_profile(leo, profile(allergies=["gluten"], intolerances=["gluten"]))
    assert restrictions(leo) == {("gluten", "allergy")}


def test_diabetes_rules_out_recipes_with_added_sugar(household, admin_user, monday):
    leo = make_diner(household, "Leo")
    flan = make_recipe(household, "Flan", [("Huevo", 4, "unit"), ("Azúcar", 100, "g")])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, flan, admin_user)
    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.OK
    services.save_profile(leo, profile(diabetes="yes"))
    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.CONFLICT
    services.save_profile(leo, profile(diabetes="no"))
    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.OK


def test_the_assistant_knows_about_diabetes(household, monday):
    leo = make_diner(household, "Leo")
    services.save_profile(leo, profile(diabetes="yes"))
    person = build_context(household, monday, monday, "chat").data["people"][0]
    assert person["health"] == ["diabetes"] and "Azúcares añadidos" in person["restrictions"]


def test_open_food_facts_marks_added_sugar():
    sweet = openfoodfacts._product({"code": "1", "allergens_tags": ["en:milk"], "ingredients_tags": ["en:cane-sugar", "en:sugar"]})
    assert sweet["allergens"] == ["added_sugar", "milk"]
    assert openfoodfacts._product({"code": "2", "ingredients_tags": ["en:tomato"]})["allergens"] == []


def test_a_wrong_answer_reopens_its_step(logged, household):
    page = logged.post(reverse("diners:create"), answers(alias="")).content.decode()
    assert 'data-start-step="0"' in page
    page = logged.post(reverse("diners:create"), answers(diet="keto")).content.decode()
    assert 'data-start-step="1"' in page
    assert not Diner.objects.filter(alias="Leo").exists()


def test_your_first_diner_comes_linked_to_your_account(logged, household, admin_user):
    admin_user.display_name = "Ana"
    admin_user.save()
    form = DinerWizardForm(household=household, user=admin_user)
    assert form.initial["linked_user"] == admin_user.pk and form.initial["alias"] == "Ana"
    assert "Ana (tú)" in logged.get(reverse("diners:create")).content.decode()
    logged.post(reverse("diners:create"), answers(alias="Ana", linked_user=admin_user.pk))
    assert Diner.objects.get(alias="Ana").linked_user == admin_user

    # Once linked, the next diner starts without an account, and yours is no longer offered.
    form = DinerWizardForm(household=household, user=admin_user)
    assert "linked_user" not in form.initial and admin_user not in form.fields["linked_user"].queryset
    logged.post(reverse("diners:create"), answers(alias="Leo"))
    assert Diner.objects.get(alias="Leo").linked_user is None


def test_only_members_of_the_household_can_be_linked(logged, household):
    outsider = make_user("fuera@example.com")
    page = logged.post(reverse("diners:create"), answers(linked_user=outsider.pk)).content.decode()
    assert 'data-start-step="0"' in page and not Diner.objects.filter(alias="Leo").exists()


def test_editing_keeps_the_link_to_the_account(logged, household, admin_user):
    ana = make_diner(household, "Ana")
    ana.linked_user = admin_user
    ana.save()
    form = DinerWizardForm(household=household, diner=ana, user=admin_user)
    assert form.initial["linked_user"] == admin_user.pk and admin_user in form.fields["linked_user"].queryset
    logged.post(reverse("diners:setup", args=[ana.pk]), answers(alias="Ana", linked_user=admin_user.pk, allergies=["egg"]))
    ana.refresh_from_db()
    assert ana.linked_user == admin_user and restrictions(ana) == {("egg", "allergy")}


def test_readers_cannot_configure_diners(client, household):
    reader = make_user("lectora@example.com")
    add_member(household, reader, Role.READER)
    leo = make_diner(household, "Leo")
    assert client.login(email=reader.email, password=PASSWORD)
    assert client.get(reverse("diners:setup", args=[leo.pk])).status_code == 403
    assert client.post(reverse("diners:create"), answers()).status_code == 403
