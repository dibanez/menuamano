from django import forms

from .models import Ingredient, Trait, normalize_name


class IngredientForm(forms.ModelForm):
    traits = forms.MultipleChoiceField(
        label="Contiene", choices=Trait.choices, required=False, widget=forms.CheckboxSelectMultiple,
    )
    aliases = forms.CharField(
        label="Otros nombres", required=False, help_text="Separados por comas. Ayudan a reconocer el ingrediente.",
    )

    class Meta:
        model = Ingredient
        fields = ("name", "category", "default_unit", "traits", "trait_info_complete", "is_processed", "aliases")

    def __init__(self, *args, household, **kwargs):
        self.household = household
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["aliases"] = ", ".join(self.instance.aliases)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = Ingredient.objects.for_household(self.household).filter(normalized_name=normalize_name(name))
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Ya existe un ingrediente con ese nombre.")
        return name

    def clean_aliases(self):
        return [a.strip() for a in self.cleaned_data["aliases"].split(",") if a.strip()]
