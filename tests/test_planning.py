from datetime import timedelta
from decimal import Decimal

import pytest

from core.choices import MealType
from diners.models import AttendancePattern, DinerRestriction
from foods.models import Trait
from planning import services as planning
from planning.models import DateException, Meal, MealMode, RecurringRule, SafetyStatus
from recipes import services as recipe_services
from shopping import services as shopping

from .factories import ingredient, make_diner, make_recipe


@pytest.fixture
def tortilla(household):
    return make_recipe(household, "Tortilla de patata", [("Huevo", 6, "unit"), ("Patata", 600, "g")], tags=["cena"])


@pytest.fixture
def arroz(household):
    return make_recipe(household, "Arroz con verduras", [("Arroz", 320, "g"), ("Calabacín", 1, "unit")], tags=["cena"])


def test_incompatible_recipe_is_blocked_and_alternatives_offered(household, admin_user, monday, tortilla, arroz):
    make_diner(household, "Nora", traits=[Trait.EGG])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)

    with pytest.raises(planning.IncompatibleRecipe) as exc:
        planning.add_recipe(meal, tortilla, admin_user)

    assert not meal.recipes.exists()
    assert "Huevo" in exc.value.result.conflicts[0].message
    assert arroz in exc.value.alternatives


def test_unknown_information_is_flagged_for_review(household, admin_user, monday):
    make_diner(household, "Leo", traits=[Trait.GLUTEN])
    recipe = make_recipe(household, "Macarrones sin gluten", [("Pasta sin gluten", 300, "g"), ("Tomate frito", 200, "g")])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.LUNCH)
    meal, result = planning.add_recipe(meal, recipe, admin_user)
    assert result.status == "unknown"
    assert meal.safety_status == SafetyStatus.UNKNOWN


def test_changing_attendees_recalculates_quantities_and_revalidates(household, admin_user, monday, tortilla):
    ana = make_diner(household, "Ana")
    luis = make_diner(household, "Luis")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.set_attendees(meal, admin_user, [ana, luis])
    planning.add_recipe(meal, tortilla, admin_user)
    sl = shopping.create_list(household, admin_user, monday, monday)
    assert sl.items.get(name="Huevo").needed_quantity == Decimal("3")

    nora = make_diner(household, "Nora", portion="0.5", traits=[Trait.EGG])
    meal = planning.set_attendees(meal, admin_user, [ana, luis, nora])

    assert sl.items.get(name="Huevo").needed_quantity == Decimal("3.75")
    assert meal.safety_status == SafetyStatus.CONFLICT
    assert any(i["person"] == "Nora" for i in meal.safety_issues)


def test_new_restriction_revalidates_existing_meals(household, admin_user, monday, tortilla):
    ana = make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, tortilla, admin_user)
    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.OK

    DinerRestriction.objects.create(diner=ana, kind=DinerRestriction.Kind.ALLERGY, trait=Trait.EGG)

    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.CONFLICT


def test_substitution_is_validated(household, admin_user, monday):
    make_diner(household, "Ana", traits=[Trait.TREE_NUTS])
    recipe = make_recipe(household, "Ensalada", [("Lechuga", 1, "unit"), ("Tomate", 2, "unit")])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.LUNCH)
    meal, _ = planning.add_recipe(meal, recipe, admin_user)
    line = meal.recipes.get().ingredients.get(ingredient__name="Tomate")

    with pytest.raises(planning.IncompatibleRecipe):
        planning.substitute_ingredient(line, ingredient("Nueces"), admin_user)

    meal, _ = planning.substitute_ingredient(line, ingredient("Pepino"), admin_user)
    line.refresh_from_db()
    assert line.ingredient.name == "Pepino" and line.substituted_for.name == "Tomate"


def test_editing_recipe_does_not_alter_planned_meal(household, admin_user, monday, tortilla):
    make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, tortilla, admin_user)

    line = tortilla.ingredients.get(ingredient__name="Huevo")
    line.quantity = Decimal("10")
    line.save()
    tortilla.name = "Tortilla jugosa"
    tortilla.save()
    recipe_services.bump_version(tortilla)

    snapshot = meal.recipes.get()
    assert snapshot.name == "Tortilla de patata"
    assert snapshot.ingredients.get(ingredient__name="Huevo").quantity == Decimal("6")
    assert snapshot.is_outdated

    planning.refresh_meal_recipe(snapshot, admin_user)
    snapshot.refresh_from_db()
    assert snapshot.name == "Tortilla jugosa" and not snapshot.is_outdated


def test_attendance_pattern_sets_default_attendees(household, monday):
    ana = make_diner(household, "Ana")
    luis = make_diner(household, "Luis")
    AttendancePattern.objects.create(diner=luis, weekday=monday.weekday(), meal_type=MealType.LUNCH, attends=False)
    meal, _ = planning.get_or_create_meal(household, monday, MealType.LUNCH)
    assert [a.diner for a in meal.attendees.all()] == [ana]


def test_regenerate_respects_locked_meals_rules_and_exceptions(household, admin_user, monday, tortilla, arroz):
    make_diner(household, "Ana")
    household.enabled_meal_types = [MealType.DINNER]
    household.save()
    friday = monday + timedelta(days=4)
    saturday = monday + timedelta(days=5)
    RecurringRule.objects.create(household=household, weekday=4, meal_type=MealType.DINNER, mode=MealMode.EAT_OUT)
    RecurringRule.objects.create(household=household, weekday=5, meal_type=MealType.DINNER, mode=MealMode.EAT_OUT)
    # The explicit exception for this Saturday prevails over the recurring rule.
    DateException.objects.create(household=household, date=saturday, meal_type=MealType.DINNER, mode=MealMode.ORDER)

    locked, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    locked, _ = planning.add_recipe(locked, tortilla, admin_user)  # manual edits lock the meal
    locked_version = Meal.objects.get(pk=locked.pk).version

    report = planning.regenerate_range(household, monday, monday + timedelta(days=6), admin_user)
    planning.regenerate_range(household, monday, monday + timedelta(days=6), admin_user)

    locked.refresh_from_db()
    assert locked.version == locked_version
    assert [r.name for r in locked.recipes.all()] == ["Tortilla de patata"]
    assert report.kept_locked == 1
    assert Meal.objects.get(household=household, date=friday).mode == MealMode.EAT_OUT
    assert Meal.objects.get(household=household, date=saturday).mode == MealMode.ORDER
    tuesday_meal = Meal.objects.get(household=household, date=monday + timedelta(days=1))
    assert tuesday_meal.mode == MealMode.COOK and tuesday_meal.recipes.count() == 1
    assert Meal.objects.filter(household=household).count() == 7  # idempotent: no duplicates


def test_regenerate_never_relaxes_restrictions(household, admin_user, monday, tortilla):
    make_diner(household, "Nora", traits=[Trait.EGG])
    household.enabled_meal_types = [MealType.DINNER]
    household.save()
    report = planning.regenerate_range(household, monday, monday, admin_user)
    meal = Meal.objects.get(household=household, date=monday)
    assert meal.mode == MealMode.PENDING and not meal.recipes.exists()
    assert report.without_recipe


def test_move_and_copy_meal(household, admin_user, monday, tortilla):
    make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, tortilla, admin_user)
    tuesday = monday + timedelta(days=1)

    copied = planning.move_or_copy(meal, admin_user, tuesday, MealType.LUNCH, copy=True)
    assert Meal.objects.filter(pk=meal.pk).exists()
    assert copied.recipes.get().name == "Tortilla de patata"

    with pytest.raises(planning.PlanningError):
        planning.move_or_copy(meal, admin_user, tuesday, MealType.LUNCH)  # occupied and locked

    moved = planning.move_or_copy(meal, admin_user, tuesday, MealType.DINNER)
    assert not Meal.objects.filter(pk=meal.pk).exists()
    assert moved.attendees.count() == 1
