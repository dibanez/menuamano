"""Bulk edits of a diner's restrictions and preferences."""

from django.db import transaction

from foods.models import Trait

from .models import DinerPreference, DinerRestriction
from .signals import batch_restriction_changes

TRAIT_LABELS = dict(Trait.choices)


def _restriction_name(restriction):
    return TRAIT_LABELS.get(restriction.trait, restriction.trait) if restriction.trait else restriction.ingredient.name


def sync_restrictions(diner, traits, ingredients, kind, label=""):
    """Make the diner's mandatory restrictions match the checked traits and ingredients.

    Returns (added names, removed names). Upcoming meals are revalidated once at the end.
    """
    traits = set(traits)
    ingredients = {i.pk: i for i in ingredients}
    added, removed = [], []
    with transaction.atomic(), batch_restriction_changes(diner.household):
        for restriction in diner.restrictions.select_related("ingredient").order_by("pk"):
            unchecked_trait = restriction.trait and restriction.trait not in traits
            unchecked_ingredient = restriction.ingredient_id and restriction.ingredient_id not in ingredients
            if unchecked_trait or unchecked_ingredient:
                removed.append(_restriction_name(restriction))
                restriction.delete()
        current = list(diner.restrictions.all())
        have_traits = {r.trait for r in current if r.trait}
        have_ingredients = {r.ingredient_id for r in current if r.ingredient_id}
        new = [DinerRestriction(diner=diner, kind=kind, trait=t, label=label) for t in sorted(traits - have_traits)]
        new += [
            DinerRestriction(diner=diner, kind=kind, ingredient=ingredients[pk], label=label)
            for pk in sorted(set(ingredients) - have_ingredients)
        ]
        DinerRestriction.objects.bulk_create(new)
        added = [_restriction_name(r) for r in new]
    return added, removed


@transaction.atomic
def sync_preferences(diner, dislikes, likes):
    """Make ingredient likes/dislikes match the checked ones. Text preferences are kept."""
    wanted = {(DinerPreference.Kind.DISLIKE, i.pk) for i in dislikes}
    wanted |= {(DinerPreference.Kind.LIKE, i.pk) for i in likes}
    current = {(p.kind, p.ingredient_id): p for p in diner.preferences.filter(ingredient__isnull=False)}
    stale = [p.pk for key, p in current.items() if key not in wanted]
    DinerPreference.objects.filter(pk__in=stale).delete()
    DinerPreference.objects.bulk_create(
        DinerPreference(diner=diner, kind=kind, ingredient_id=pk) for kind, pk in sorted(wanted - set(current))
    )
    return len(wanted - set(current)), len(stale)
