from datetime import date

from django import forms

from accounts.models import User
from foods.models import DIET_PRESETS, Ingredient

from .models import Diner, DinerPreference, DinerRestriction, WeightMeasurement

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


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


class RestrictionForm(forms.ModelForm):
    class Meta:
        model = DinerRestriction
        fields = ("kind", "trait", "ingredient", "label")
        labels = {"trait": "Qué no puede tomar", "ingredient": "O un ingrediente concreto"}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ingredient"].queryset = Ingredient.objects.for_household(household)
        self.fields["trait"].choices = [("", "—")] + list(self.fields["trait"].choices)[1:]

    def clean(self):
        data = super().clean()
        if not data.get("trait") and not data.get("ingredient"):
            raise forms.ValidationError("Elige un alérgeno o rasgo, o bien un ingrediente concreto.")
        return data


class DietPresetForm(forms.Form):
    preset = forms.ChoiceField(label="Dieta", choices=[(k, v[0]) for k, v in DIET_PRESETS.items()])


class PreferenceForm(forms.ModelForm):
    class Meta:
        model = DinerPreference
        fields = ("kind", "ingredient", "text")

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ingredient"].queryset = Ingredient.objects.for_household(household)
        self.fields["ingredient"].required = False

    def clean(self):
        data = super().clean()
        if not data.get("ingredient") and not data.get("text"):
            raise forms.ValidationError("Indica un ingrediente o describe la preferencia.")
        return data


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
