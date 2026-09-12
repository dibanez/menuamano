import pytest
from django.urls import reverse

from core.choices import MealType
from foods import compatibility
from foods.models import Ingredient, Trait, expand_traits
from planning import services as planning

from .factories import PASSWORD, ingredient, make_diner, make_recipe


def test_legumes_can_be_restricted():
    assert (Trait.LEGUMES.value, "Legumbres") in Trait.choices


@pytest.mark.parametrize("trait", [Trait.SOY, Trait.PEANUT, Trait.LUPIN])
def test_soy_peanut_and_lupin_are_legumes(trait):
    assert Trait.LEGUMES in expand_traits([trait])
    assert Trait.PEANUT not in expand_traits([Trait.LEGUMES])  # not the other way round


@pytest.mark.parametrize("name", [
    "Lentejas", "Garbanzos cocidos", "Alubias blancas", "Guisantes congelados", "Tofu", "Cacahuetes", "Salsa de soja",
])
def test_catalogue_pulses_carry_the_legumes_trait(db, name):
    assert "legumes" in ingredient(name).traits


def test_household_ingredients_get_legumes_when_they_contain_soy(household):
    edamame = Ingredient.objects.create(household=household, name="Edamame", traits=[Trait.SOY], trait_info_complete=True)
    assert "legumes" in edamame.traits


def test_legume_restriction_blocks_lentils_and_tofu(household, admin_user, monday):
    make_diner(household, "Lucía", traits=[Trait.LEGUMES])
    lentejas = make_recipe(household, "Lentejas", [("Lentejas", 300, "g")])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.LUNCH)
    with pytest.raises(planning.IncompatibleRecipe):
        planning.add_recipe(meal, lentejas, admin_user)
    rules = compatibility.PersonRules("Lucía", frozenset([Trait.LEGUMES]))
    tofu = compatibility.facts_for_ingredient(ingredient("Tofu"))
    assert compatibility.evaluate([tofu], [rules]).status == compatibility.CONFLICT


def test_legumes_can_be_checked_in_the_profile(client, household, admin_user):
    diner = make_diner(household, "Lucía")
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(reverse("diners:restrictions_save", args=[diner.pk]), {"r-traits": ["legumes"], "r-kind": "allergy"})
    assert diner.restrictions.get().get_trait_display() == "Legumbres"
