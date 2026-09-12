"""Dietary compatibility rules, independent from any AI prompt.

Principles:
* A known trait that matches a mandatory restriction is a CONFLICT.
* Missing information is UNKNOWN, never "safe": an ingredient whose traits have not been
  reviewed cannot be accepted automatically for someone with restrictions.
* OK only means "compatible according to the data we have". It is never a guarantee about
  traces or cross-contamination, so callers always show the labelling reminder.
"""

from dataclasses import dataclass, field

from .models import Trait

OK = "ok"
UNKNOWN = "unknown"
CONFLICT = "conflict"

LEVEL_CONFLICT = "conflict"
LEVEL_UNKNOWN = "unknown"
LEVEL_WARNING = "warning"

TRAIT_LABELS = dict(Trait.choices)

LABEL_REMINDER = (
    "La comprobación usa los datos registrados en menuamano. No garantiza la ausencia de trazas "
    "ni de contaminación cruzada: revisa siempre el etiquetado y cómo se prepara."
)


@dataclass(frozen=True)
class IngredientFacts:
    ingredient_id: int | None
    name: str
    traits: frozenset
    info_complete: bool
    is_processed: bool = False
    optional: bool = False
    substituted_for: str = ""


@dataclass(frozen=True)
class PersonRules:
    label: str
    traits: frozenset = frozenset()
    ingredient_ids: frozenset = frozenset()
    ingredient_names: tuple = ()
    unverified_notes: str = ""

    @property
    def has_checkable_rules(self):
        return bool(self.traits or self.ingredient_ids)


@dataclass
class Issue:
    level: str
    person: str
    ingredient: str
    message: str
    trait: str = ""

    def as_dict(self):
        return {
            "level": self.level,
            "person": self.person,
            "ingredient": self.ingredient,
            "message": self.message,
            "trait": self.trait,
        }


@dataclass
class CompatibilityResult:
    status: str = OK
    issues: list = field(default_factory=list)

    @property
    def conflicts(self):
        return [i for i in self.issues if i.level == LEVEL_CONFLICT]

    @property
    def unknowns(self):
        return [i for i in self.issues if i.level == LEVEL_UNKNOWN]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == LEVEL_WARNING]

    def issues_as_dicts(self):
        return [i.as_dict() for i in self.issues]


def _labels(traits):
    return ", ".join(sorted(TRAIT_LABELS.get(t, t).lower() for t in traits))


def evaluate(ingredients, people):
    """Check every ingredient (substitutions included) against every attendee."""
    issues = []
    for person in people:
        for ing in ingredients:
            suffix = " (ingrediente opcional: quítalo o sustitúyelo)" if ing.optional else ""
            if ing.substituted_for:
                suffix += f" (sustituye a {ing.substituted_for})"
            if ing.ingredient_id is not None and ing.ingredient_id in person.ingredient_ids:
                issues.append(
                    Issue(LEVEL_CONFLICT, person.label, ing.name,
                          f"{person.label} no puede tomar {ing.name}{suffix}.")
                )
                continue
            matched = person.traits & ing.traits
            if matched:
                for trait in sorted(matched):
                    issues.append(
                        Issue(LEVEL_CONFLICT, person.label, ing.name,
                              f"{ing.name} contiene {TRAIT_LABELS.get(trait, trait).lower()}, "
                              f"incompatible con {person.label}{suffix}.", trait)
                    )
                continue
            if person.traits and not ing.info_complete:
                issues.append(
                    Issue(LEVEL_UNKNOWN, person.label, ing.name,
                          f"No hay información suficiente sobre {ing.name} para confirmar que no contiene "
                          f"{_labels(person.traits)} ({person.label}). Revísalo antes de aceptarlo{suffix}.")
                )
            elif person.traits and ing.is_processed:
                issues.append(
                    Issue(LEVEL_WARNING, person.label, ing.name,
                          f"{ing.name} es un producto procesado: comprueba la etiqueta de la marca que compres "
                          f"({person.label}: {_labels(person.traits)}).")
                )
        if person.unverified_notes:
            issues.append(
                Issue(LEVEL_WARNING, person.label, "",
                      f"{person.label} tiene observaciones que no se comprueban automáticamente: "
                      f"«{person.unverified_notes}».")
            )

    if any(i.level == LEVEL_CONFLICT for i in issues):
        status = CONFLICT
    elif any(i.level == LEVEL_UNKNOWN for i in issues):
        status = UNKNOWN
    else:
        status = OK
    return CompatibilityResult(status=status, issues=issues)


# --- Adapters from models -----------------------------------------------------------------


def facts_for_ingredient(ingredient, optional=False, substituted_for=None):
    return IngredientFacts(
        ingredient_id=ingredient.pk,
        name=ingredient.name,
        traits=frozenset(ingredient.traits),
        info_complete=ingredient.trait_info_complete,
        is_processed=ingredient.is_processed,
        optional=optional,
        substituted_for=substituted_for.name if substituted_for else "",
    )


def rules_for_diner(diner):
    """Mandatory restrictions of a diner. Preferences (dislikes) are deliberately excluded."""
    traits, ingredient_ids, names = set(), set(), []
    for restriction in diner.restrictions.all():
        if restriction.trait:
            traits.add(restriction.trait)
        if restriction.ingredient_id:
            ingredient_ids.add(restriction.ingredient_id)
            names.append(restriction.ingredient.name)
    return PersonRules(
        label=diner.alias,
        traits=frozenset(traits),
        ingredient_ids=frozenset(ingredient_ids),
        ingredient_names=tuple(names),
        unverified_notes="",
    )


def rules_for_guest(name, traits, notes=""):
    return PersonRules(label=f"{name} (invitado)", traits=frozenset(traits), unverified_notes=notes)


def rules_for_attendee(attendee):
    if attendee.diner_id:
        return rules_for_diner(attendee.diner)
    return rules_for_guest(attendee.guest_name, attendee.guest_traits, attendee.guest_notes)
