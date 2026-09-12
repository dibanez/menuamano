"""Household label reviews of catalogue ingredients (see IngredientReview)."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import IngredientReview


def reviews_for(household):
    """{ingredient_id: IngredientReview} for one household (accepts a household or its id)."""
    household_id = getattr(household, "pk", household)
    if not household_id:
        return {}
    return {r.ingredient_id: r for r in IngredientReview.objects.filter(household_id=household_id)}


def revalidate_meals_using(household, ingredient):
    """Upcoming meals of the household that use the ingredient, directly or through leftovers."""
    from planning.models import Meal
    from planning.services import revalidate_meal

    meals = (
        Meal.objects.filter(household=household, date__gte=timezone.localdate())
        .filter(
            Q(recipes__ingredients__ingredient=ingredient)
            | Q(leftovers_from__recipes__ingredients__ingredient=ingredient)
        )
        .distinct()
    )
    for meal in meals:
        revalidate_meal(meal)


@transaction.atomic
def save_review(household, ingredient, user, traits, note=""):
    review, _ = IngredientReview.objects.update_or_create(
        household=household, ingredient=ingredient,
        defaults={"traits": list(traits), "note": note, "reviewed_by": user},
    )
    revalidate_meals_using(household, ingredient)
    return review


@transaction.atomic
def delete_review(review):
    household, ingredient = review.household, review.ingredient
    review.delete()
    revalidate_meals_using(household, ingredient)
