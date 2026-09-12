"""Plain helper functions to build test data (no external factory library)."""

from decimal import Decimal

from accounts.models import User
from core.legal import record_consent
from diners.models import Diner, DinerRestriction
from foods.models import Ingredient
from households.models import Household, Membership, Role
from recipes.models import Recipe, RecipeIngredient, RecipeStep

PASSWORD = "a-strong-test-password"


def make_user(email, consented=True):
    user = User.objects.create_user(email=email, password=PASSWORD)
    if consented:
        record_consent(user)
    return user


def make_household(name="Casa", admin=None, role=Role.ADMIN):
    household = Household.objects.create(name=name)
    if admin is not None:
        Membership.objects.create(user=admin, household=household, role=role)
    return household


def add_member(household, user, role):
    return Membership.objects.create(user=user, household=household, role=role)


def ingredient(name):
    return Ingredient.objects.get(household__isnull=True, name=name)


def make_diner(household, alias, portion="1", traits=(), avoid=(), **extra):
    diner = Diner.objects.create(household=household, alias=alias, portion_factor=Decimal(portion), **extra)
    for trait in traits:
        DinerRestriction.objects.create(diner=diner, kind=DinerRestriction.Kind.ALLERGY, trait=trait)
    for name in avoid:
        DinerRestriction.objects.create(diner=diner, kind=DinerRestriction.Kind.OTHER, ingredient=ingredient(name))
    return diner


def make_recipe(household, name, lines, base_servings=4, steps=("Preparar.",), tags=(), minutes=(10, 10)):
    recipe = Recipe.objects.create(
        household=household, name=name, base_servings=base_servings, tags=list(tags),
        prep_minutes=minutes[0], cook_minutes=minutes[1],
    )
    for order, line in enumerate(lines):
        ing_name, quantity, unit = line[:3]
        RecipeIngredient.objects.create(
            recipe=recipe, ingredient=ingredient(ing_name),
            quantity=None if quantity is None else Decimal(str(quantity)), unit=unit, order=order,
        )
    for order, text in enumerate(steps):
        RecipeStep.objects.create(recipe=recipe, order=order, text=text)
    return recipe
