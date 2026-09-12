from django.db import transaction
from django.db.models import F, Prefetch

from foods.compatibility import evaluate, facts_for_ingredient
from planning.models import MealRecipe, MealRecipeIngredient

from .models import Recipe, RecipeIngredient

MEAL_TYPE_TAGS = {"breakfast": "desayuno", "lunch": "comida", "snack": "merienda", "dinner": "cena"}


def recipes_for_household(household, include_archived=False):
    qs = Recipe.objects.filter(household=household)
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return qs.prefetch_related(
        Prefetch("ingredients", queryset=RecipeIngredient.objects.select_related("ingredient"))
    )


def recipe_facts(recipe):
    return [facts_for_ingredient(ri.ingredient, optional=ri.optional) for ri in recipe.ingredients.all()]


def check_recipe(recipe, people):
    return evaluate(recipe_facts(recipe), people)


def fits_meal_type(recipe, meal_type):
    """Recipes tagged with meal types only fit those; untagged ones fit lunch and dinner."""
    tagged = {tag for tag in recipe.tags if tag in MEAL_TYPE_TAGS.values()}
    if not tagged:
        return meal_type in ("lunch", "dinner")
    return MEAL_TYPE_TAGS.get(meal_type) in tagged


def bump_version(recipe):
    """Mark a content change. Meals keep the snapshot of the version they used."""
    Recipe.objects.filter(pk=recipe.pk).update(version=F("version") + 1)
    recipe.refresh_from_db(fields=["version"])


@transaction.atomic
def snapshot_into_meal(meal, recipe, order=None, servings_override=None):
    """Copy the current recipe content into the meal."""
    if order is None:
        order = meal.recipes.count()
    meal_recipe = MealRecipe.objects.create(
        meal=meal,
        recipe=recipe,
        recipe_version=recipe.version,
        name=recipe.name,
        base_servings=recipe.base_servings,
        servings_override=servings_override,
        prep_minutes=recipe.prep_minutes,
        cook_minutes=recipe.cook_minutes,
        steps=[step.text for step in recipe.steps.all()],
        order=order,
    )
    _copy_ingredients(recipe, meal_recipe)
    return meal_recipe


def _copy_ingredients(recipe, meal_recipe):
    MealRecipeIngredient.objects.bulk_create(
        MealRecipeIngredient(
            meal_recipe=meal_recipe,
            ingredient_id=ri.ingredient_id,
            quantity=ri.quantity,
            unit=ri.unit,
            note=ri.note,
            optional=ri.optional,
            order=index,
        )
        for index, ri in enumerate(recipe.ingredients.all())
    )


@transaction.atomic
def refresh_snapshot(meal_recipe):
    """Explicitly update a meal's copy to the latest recipe version (drops meal-level tweaks)."""
    recipe = meal_recipe.recipe
    if recipe is None:
        return meal_recipe
    meal_recipe.ingredients.all().delete()
    meal_recipe.recipe_version = recipe.version
    meal_recipe.name = recipe.name
    meal_recipe.base_servings = recipe.base_servings
    meal_recipe.prep_minutes = recipe.prep_minutes
    meal_recipe.cook_minutes = recipe.cook_minutes
    meal_recipe.steps = [step.text for step in recipe.steps.all()]
    meal_recipe.save()
    _copy_ingredients(recipe, meal_recipe)
    return meal_recipe
