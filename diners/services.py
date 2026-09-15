"""Bulk edits of a diner's restrictions and preferences."""

from django.db import transaction

from foods.models import ALLERGEN_TRAITS, DIET_PRESETS, Trait

from .models import DinerPreference, DinerRestriction
from .signals import batch_restriction_changes

TRAIT_LABELS = dict(Trait.choices)
Kind = DinerRestriction.Kind

# The configurator's questions and the traits each one can mark.
ALLERGY_TRAITS = [trait for trait in Trait.values if trait in ALLERGEN_TRAITS or trait == Trait.LEGUMES]
INTOLERANCE_TRAITS = [Trait.LACTOSE, Trait.GLUTEN]
EXTRA_DIETS = {Trait.PORK: "no_pork", Trait.ALCOHOL: "no_alcohol"}
VEGETARIAN_TRAITS = set(DIET_PRESETS["vegetarian"][1])
# When two answers mark the same trait, the restriction keeps the first kind of this list.
KIND_PRIORITY = [Kind.ALLERGY, Kind.INTOLERANCE, Kind.DIABETES, Kind.DIET, Kind.OTHER]


def wizard_initial(diner):
    """The configurator's answers that describe what the diner has now."""
    kinds = {r.trait: r.kind for r in diner.restrictions.all() if r.trait}
    traits = set(kinds)
    if Trait.ANIMAL_ORIGIN in traits:
        diet = "vegan"
    elif VEGETARIAN_TRAITS <= traits:
        diet = "vegetarian"
    elif Trait.MEAT in traits:
        diet = "pescatarian"
    else:
        diet = "omnivore"
    by_diet = set(DIET_PRESETS[diet][1]) if diet in DIET_PRESETS else set()
    extras, allergies, intolerances = [], [], []
    for trait, kind in sorted(kinds.items()):
        if trait == Trait.ADDED_SUGAR or (trait in by_diet and kind == Kind.DIET):
            continue
        if trait in EXTRA_DIETS:
            extras.append(EXTRA_DIETS[trait])
        elif trait in INTOLERANCE_TRAITS and (kind == Kind.INTOLERANCE or trait not in ALLERGY_TRAITS):
            intolerances.append(trait)
        elif trait in ALLERGY_TRAITS:
            allergies.append(trait)
    return {
        "alias": diner.alias,
        "birth_date": diner.birth_date,
        "portion": f"{diner.portion_factor:.2f}",
        "diet": diet,
        "extras": extras,
        "allergies": allergies,
        "intolerances": intolerances,
        "ingredients": [r.ingredient_id for r in diner.restrictions.all() if r.ingredient_id],
        "diabetes": "yes" if Trait.ADDED_SUGAR in traits else "no",
        "linked_user": diner.linked_user_id,
    }


def _wanted_restrictions(data):
    """trait → (kind, label) for every restriction the configurator's answers imply."""
    wanted = {}

    def want(trait, kind, label=""):
        if trait not in wanted or KIND_PRIORITY.index(kind) < KIND_PRIORITY.index(wanted[trait][0]):
            wanted[trait] = (kind, label)

    for key in [data["diet"], *data["extras"]]:
        if key in DIET_PRESETS:
            label, traits = DIET_PRESETS[key]
            for trait in traits:
                want(trait, Kind.DIET, label)
    for trait in data["intolerances"]:
        want(trait, Kind.INTOLERANCE)
    for trait in data["allergies"]:
        want(trait, Kind.ALLERGY)
    if data["diabetes"] == "yes":
        want(Trait.ADDED_SUGAR, Kind.DIABETES)
    return wanted


def save_profile(diner, data):
    """Save the configurator's answers: the diner's details and exactly the restrictions they imply.

    Restrictions that still apply keep their note unless their kind changes. Upcoming meals are
    revalidated once at the end.
    """
    wanted = _wanted_restrictions(data)
    ingredients = {i.pk: i for i in data["ingredients"]}
    diner.alias, diner.birth_date, diner.portion_factor = data["alias"], data["birth_date"], data["portion"]
    if "linked_user" in data:
        diner.linked_user = data["linked_user"]
    with transaction.atomic(), batch_restriction_changes(diner.household):
        diner.save()
        for restriction in diner.restrictions.order_by("pk"):
            if restriction.trait and restriction.trait in wanted:
                kind, label = wanted.pop(restriction.trait)
                if restriction.kind != kind:
                    restriction.kind, restriction.label = kind, label
                    restriction.save(update_fields=["kind", "label"])
            elif restriction.ingredient_id and restriction.ingredient_id in ingredients:
                ingredients.pop(restriction.ingredient_id)
            else:
                restriction.delete()
        DinerRestriction.objects.bulk_create(
            [DinerRestriction(diner=diner, kind=kind, trait=trait, label=label) for trait, (kind, label) in sorted(wanted.items())]
            + [DinerRestriction(diner=diner, kind=Kind.OTHER, ingredient=ingredient) for _, ingredient in sorted(ingredients.items())]
        )
    return diner


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
