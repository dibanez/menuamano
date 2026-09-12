from foods import compatibility as c
from foods.models import Ingredient, Trait, expand_traits


def facts(name, traits=(), complete=True, processed=False, ingredient_id=None, **kw):
    return c.IngredientFacts(ingredient_id, name, frozenset(traits), complete, processed, **kw)


def person(label="Nora", traits=(), ingredient_ids=(), notes=""):
    return c.PersonRules(label, frozenset(traits), frozenset(ingredient_ids), (), notes)


def test_known_allergen_is_conflict():
    result = c.evaluate([facts("Huevo", [Trait.EGG])], [person(traits=[Trait.EGG])])
    assert result.status == c.CONFLICT
    assert "Huevo" in result.conflicts[0].message


def test_specific_ingredient_restriction_is_conflict():
    result = c.evaluate([facts("Apio", [Trait.CELERY], ingredient_id=7)], [person(ingredient_ids=[7])])
    assert result.status == c.CONFLICT


def test_incomplete_information_is_unknown_not_safe():
    result = c.evaluate([facts("Tomate frito", complete=False)], [person(traits=[Trait.GLUTEN])])
    assert result.status == c.UNKNOWN
    assert result.unknowns


def test_incomplete_information_is_irrelevant_without_restrictions():
    result = c.evaluate([facts("Tomate frito", complete=False)], [person()])
    assert result.status == c.OK


def test_processed_but_reviewed_product_only_warns():
    result = c.evaluate([facts("Mostaza", [Trait.MUSTARD], processed=True)], [person(traits=[Trait.GLUTEN])])
    assert result.status == c.OK
    assert result.warnings


def test_conflict_wins_over_unknown():
    ingredients = [facts("Tomate frito", complete=False), facts("Queso", [Trait.MILK])]
    result = c.evaluate(ingredients, [person(traits=[Trait.MILK])])
    assert result.status == c.CONFLICT


def test_substitution_is_checked_like_any_ingredient():
    sub = facts("Nueces", [Trait.TREE_NUTS], substituted_for="Piñones")
    result = c.evaluate([sub], [person(traits=[Trait.TREE_NUTS])])
    assert result.status == c.CONFLICT
    assert "sustituye a Piñones" in result.conflicts[0].message


def test_optional_ingredient_is_not_relaxed():
    result = c.evaluate([facts("Cacahuetes", [Trait.PEANUT], optional=True)], [person(traits=[Trait.PEANUT])])
    assert result.status == c.CONFLICT


def test_guest_restrictions_are_checked():
    guest = c.rules_for_guest("Marta", [Trait.FISH])
    result = c.evaluate([facts("Merluza", [Trait.FISH, Trait.ANIMAL_ORIGIN])], [person(), guest])
    assert result.status == c.CONFLICT
    assert result.conflicts[0].person == "Marta (invitado)"


def test_implied_traits_make_diets_consistent():
    assert expand_traits([Trait.PORK]) >= {Trait.MEAT, Trait.ANIMAL_ORIGIN}
    assert Trait.MILK in expand_traits([Trait.LACTOSE])


def test_ingredient_save_expands_traits(db):
    ing = Ingredient.objects.create(name="Panceta", traits=[Trait.PORK], trait_info_complete=True)
    assert set(ing.traits) == {Trait.PORK, Trait.MEAT, Trait.ANIMAL_ORIGIN}


def test_new_household_ingredient_defaults_to_unknown(db):
    ing = Ingredient.objects.create(name="Salsa misteriosa")
    result = c.evaluate([c.facts_for_ingredient(ing)], [person(traits=[Trait.SESAME])])
    assert result.status == c.UNKNOWN


def test_unverified_notes_are_flagged():
    result = c.evaluate([facts("Arroz")], [person(notes="nada picante")])
    assert result.status == c.OK
    assert "no se comprueban automáticamente" in result.warnings[0].message
