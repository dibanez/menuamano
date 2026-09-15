from datetime import date
from decimal import Decimal

from django import forms
from django.db.models import Case, IntegerField, Value, When

from accounts.models import User
from foods.models import DIET_PRESETS, Ingredient, Trait

from .models import Diner, DinerPreference, DinerRestriction, WeightMeasurement
from .services import ALLERGY_TRAITS, wizard_initial

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def selected_first(queryset, ids):
    """Checked ingredients first, then alphabetical: long lists stay easy to review."""
    return queryset.annotate(
        _rank=Case(When(pk__in=list(ids) or [0], then=Value(0)), default=Value(1), output_field=IntegerField())
    ).order_by("_rank", "name")


class DinerForm(forms.ModelForm):
    class Meta:
        model = Diner
        fields = ("alias", "birth_date", "portion_factor", "height_cm", "notes", "linked_user", "is_active")
        widgets = {"birth_date": DATE_WIDGET, "notes": forms.Textarea(attrs={"rows": 2})}
        help_texts = {
            "birth_date": "Opcional. Solo se usa para mostrar la edad; nunca se envía completa a la IA.",
            "height_cm": "Opcional.",
            "linked_user": "Si esta persona tiene cuenta, podrá gestionar quién ve su historial de peso.",
        }

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["linked_user"].queryset = User.objects.filter(memberships__household=household).order_by("email")
        self.fields["linked_user"].required = False

    def clean_birth_date(self):
        value = self.cleaned_data.get("birth_date")
        if value and value > date.today():
            raise forms.ValidationError("La fecha de nacimiento no puede estar en el futuro.")
        return value


PORTION_CHOICES = [
    ("0.50", "Pequeña (niños pequeños)"),
    ("0.75", "Infantil"),
    ("1.00", "Normal (adulto)"),
    ("1.25", "Grande (mucho apetito)"),
]
DIET_CHOICES = [
    ("omnivore", "Come de todo"),
    ("vegetarian", "Vegetariana (sin carne ni pescado)"),
    ("vegan", "Vegana (nada de origen animal)"),
    ("pescatarian", "Pescetariana (sin carne, con pescado)"),
]
EXTRA_CHOICES = [("no_pork", "Sin cerdo"), ("no_alcohol", "Sin alcohol")]
INTOLERANCE_CHOICES = [(Trait.LACTOSE, "Lactosa"), (Trait.GLUTEN, "Gluten (celiaquía o sensibilidad)")]
DIABETES_CHOICES = [("no", "No"), ("yes", "Sí")]


class DinerWizardForm(forms.Form):
    """The configurator: who the person is, their diet, allergies, intolerances and diabetes."""

    alias = forms.CharField(label="Nombre o alias", max_length=60)
    birth_date = forms.DateField(
        label="Fecha de nacimiento", required=False, widget=DATE_WIDGET,
        help_text="Opcional. Solo se usa para saber la edad; nunca se envía completa a la IA.",
    )
    portion = forms.ChoiceField(
        label="¿Cuánto suele comer?", widget=forms.RadioSelect,
        help_text="Sirve para calcular las cantidades de la compra.",
    )
    diet = forms.ChoiceField(label="Tipo de alimentación", choices=DIET_CHOICES, widget=forms.RadioSelect)
    extras = forms.MultipleChoiceField(
        label="Además", choices=EXTRA_CHOICES, required=False, widget=forms.CheckboxSelectMultiple,
    )
    allergies = forms.MultipleChoiceField(
        label="Alergias", choices=[(t, Trait(t).label) for t in ALLERGY_TRAITS], required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    intolerances = forms.MultipleChoiceField(
        label="Intolerancias", choices=INTOLERANCE_CHOICES, required=False, widget=forms.CheckboxSelectMultiple,
    )
    ingredients = forms.ModelMultipleChoiceField(
        label="Otros ingredientes que no puede tomar", queryset=Ingredient.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    diabetes = forms.ChoiceField(label="Diabetes", choices=DIABETES_CHOICES, widget=forms.RadioSelect)
    linked_user = forms.ModelChoiceField(
        label="Cuenta en menuamano", queryset=User.objects.none(), required=False, empty_label="Sin cuenta",
        help_text="Si esta persona tiene cuenta, podrá gestionar quién ve su historial de peso.",
    )

    def __init__(self, *args, household, diner=None, user=None, **kwargs):
        if diner:
            initial = wizard_initial(diner)
        else:
            initial = {"portion": "1.00", "diet": "omnivore", "diabetes": "no"}
            # The first diner a person creates is usually themselves: their account comes linked.
            if user is not None and not household.diners.filter(linked_user=user).exists():
                initial["linked_user"] = user.pk
                if user.display_name:
                    initial["alias"] = user.display_name
        kwargs.setdefault("initial", initial)
        super().__init__(*args, **kwargs)
        # Members whose account is not linked to another diner of this household yet.
        taken = household.diners.exclude(pk=diner.pk if diner else None).exclude(linked_user=None)
        self.fields["linked_user"].queryset = (
            User.objects.filter(memberships__household=household)
            .exclude(pk__in=taken.values_list("linked_user", flat=True)).order_by("email")
        )
        self.fields["linked_user"].label_from_instance = (
            lambda member: f"{member} (tú)" if user is not None and member.pk == user.pk else str(member)
        )
        portions = list(PORTION_CHOICES)
        if initial["portion"] not in dict(portions):  # a custom size set in «Más datos»
            number = initial["portion"].rstrip("0").rstrip(".").replace(".", ",")
            portions.append((initial["portion"], f"La actual: {number}"))
        self.fields["portion"].choices = portions
        self.fields["ingredients"].queryset = selected_first(
            Ingredient.objects.for_household(household), initial.get("ingredients", [])
        )

    def clean_birth_date(self):
        value = self.cleaned_data.get("birth_date")
        if value and value > date.today():
            raise forms.ValidationError("La fecha de nacimiento no puede estar en el futuro.")
        return value

    def clean_portion(self):
        return Decimal(self.cleaned_data["portion"])


class RestrictionsForm(forms.Form):
    """All mandatory restrictions of a diner at once: what is checked is what applies."""

    traits = forms.MultipleChoiceField(
        label="Alérgenos y otros rasgos", choices=Trait.choices, required=False, widget=forms.CheckboxSelectMultiple,
    )
    ingredients = forms.ModelMultipleChoiceField(
        label="Ingredientes concretos", queryset=Ingredient.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    kind = forms.ChoiceField(
        label="Tipo para las que marques ahora", choices=DinerRestriction.Kind.choices,
        initial=DinerRestriction.Kind.ALLERGY,
    )
    label = forms.CharField(label="Nota (opcional)", max_length=80, required=False)

    def __init__(self, *args, diner, **kwargs):
        restrictions = list(diner.restrictions.all())
        ingredient_ids = [r.ingredient_id for r in restrictions if r.ingredient_id]
        kwargs.setdefault("initial", {
            "traits": sorted({r.trait for r in restrictions if r.trait}),
            "ingredients": ingredient_ids,
        })
        super().__init__(*args, **kwargs)
        self.fields["ingredients"].queryset = selected_first(
            Ingredient.objects.for_household(diner.household), ingredient_ids
        )


class PreferencesForm(forms.Form):
    """Negotiable likes and dislikes, several ingredients at once."""

    dislikes = forms.ModelMultipleChoiceField(
        label="No le gusta", queryset=Ingredient.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
    )
    likes = forms.ModelMultipleChoiceField(
        label="Le gusta", queryset=Ingredient.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, diner, **kwargs):
        preferences = list(diner.preferences.filter(ingredient__isnull=False))
        dislike_ids = [p.ingredient_id for p in preferences if p.kind == DinerPreference.Kind.DISLIKE]
        like_ids = [p.ingredient_id for p in preferences if p.kind == DinerPreference.Kind.LIKE]
        kwargs.setdefault("initial", {"dislikes": dislike_ids, "likes": like_ids})
        super().__init__(*args, **kwargs)
        ingredients = Ingredient.objects.for_household(diner.household)
        self.fields["dislikes"].queryset = selected_first(ingredients, dislike_ids)
        self.fields["likes"].queryset = selected_first(ingredients, like_ids)

    def clean(self):
        data = super().clean()
        both = set(data.get("dislikes") or []) & set(data.get("likes") or [])
        if both:
            names = ", ".join(sorted(i.name for i in both))
            raise forms.ValidationError(f"No puede estar a la vez en «le gusta» y «no le gusta»: {names}.")
        return data


class TextPreferenceForm(forms.ModelForm):
    """Preferences that are not a single ingredient, e.g. «platos de cuchara»."""

    class Meta:
        model = DinerPreference
        fields = ("kind", "text")
        labels = {"text": "Otra preferencia"}
        help_texts = {"text": "Por ejemplo: «platos de cuchara», «nada muy picante»."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = DinerPreference.Kind.choices  # no empty "---------" option

    def clean_text(self):
        text = self.cleaned_data["text"].strip()
        if not text:
            raise forms.ValidationError("Describe la preferencia.")
        return text


class DietPresetForm(forms.Form):
    preset = forms.ChoiceField(label="Dieta", choices=[(k, v[0]) for k, v in DIET_PRESETS.items()])


class WeightForm(forms.ModelForm):
    class Meta:
        model = WeightMeasurement
        fields = ("measured_on", "weight_kg")
        widgets = {"measured_on": DATE_WIDGET}

    def clean_measured_on(self):
        value = self.cleaned_data["measured_on"]
        if value > date.today():
            raise forms.ValidationError("La fecha no puede estar en el futuro.")
        return value


class GrantForm(forms.Form):
    user = forms.ModelChoiceField(label="Persona del hogar", queryset=User.objects.none())

    def __init__(self, *args, diner, **kwargs):
        super().__init__(*args, **kwargs)
        excluded = list(diner.health_access.values_list("user_id", flat=True))
        if diner.linked_user_id:
            excluded.append(diner.linked_user_id)
        self.fields["user"].queryset = (
            User.objects.filter(memberships__household=diner.household).exclude(pk__in=excluded).order_by("email")
        )
