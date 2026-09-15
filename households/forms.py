from django import forms

from core.choices import MealType

from .models import Household


class HouseholdForm(forms.ModelForm):
    enabled_meal_types = forms.MultipleChoiceField(
        label="Comidas que planificáis", choices=MealType.choices, widget=forms.CheckboxSelectMultiple,
        help_text="Las comidas desactivadas no aparecen en el calendario ni se regeneran.",
    )

    class Meta:
        model = Household
        fields = ("name", "enabled_meal_types")
        labels = {"name": "Nombre del hogar"}

    def clean_enabled_meal_types(self):
        values = self.cleaned_data["enabled_meal_types"]
        if not values:
            raise forms.ValidationError("Activa al menos un tipo de comida.")
        return values


class NewHouseholdForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = ("name",)
        labels = {"name": "Nombre del hogar"}
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Casa, piso de la calle Mayor…"})}
