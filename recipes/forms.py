from django import forms
from django.forms import inlineformset_factory

from foods.models import Ingredient

from .models import Recipe, RecipeIngredient, RecipeStep


class RecipeForm(forms.ModelForm):
    source_url = forms.URLField(
        label="Receta original", required=False, max_length=500, assume_scheme="https",
        help_text="Enlace a la página de donde viene.",
    )

    class Meta:
        model = Recipe
        fields = (
            "name", "description", "base_servings", "prep_minutes", "cook_minutes", "difficulty", "equipment",
            "advance_note", "tags", "source_url",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}
        help_texts = {
            "tags": "Separadas por comas. Usa desayuno, comida, merienda o cena para indicar cuándo encaja; "
            "sin ninguna, se propone para comidas y cenas.",
            "equipment": "Por ejemplo: horno, sartén grande.",
        }

    def clean_tags(self):
        return sorted({t.strip().lower() for t in self.cleaned_data.get("tags") or [] if t.strip()})


class RecipeIngredientForm(forms.ModelForm):
    class Meta:
        model = RecipeIngredient
        fields = ("ingredient", "quantity", "unit", "note", "optional")
        widgets = {"quantity": forms.NumberInput(attrs={"step": "any", "min": "0", "inputmode": "decimal"})}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        # Only shared catalogue and this household's ingredients can be referenced.
        self.fields["ingredient"].queryset = Ingredient.objects.for_household(household).order_by("name")


RecipeIngredientFormSet = inlineformset_factory(
    Recipe, RecipeIngredient, form=RecipeIngredientForm, extra=2, can_delete=True
)

RecipeStepFormSet = inlineformset_factory(
    Recipe, RecipeStep, fields=("text",), extra=2, can_delete=True,
    widgets={"text": forms.Textarea(attrs={"rows": 2})},
)


class AddToMealForm(forms.Form):
    date = forms.DateField(label="Día", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    meal_type = forms.ChoiceField(label="Comida")

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        from core.choices import MealType

        self.fields["meal_type"].choices = [(mt, MealType(mt).label) for mt in household.meal_types]
