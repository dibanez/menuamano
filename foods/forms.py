from django import forms

from .models import CONVERTIBLE_UNITS, Ingredient, Trait, Unit, UnitConversion, normalize_name


class ConversionForm(forms.ModelForm):
    class Meta:
        model = UnitConversion
        fields = ("unit", "grams", "note")
        labels = {"unit": "Unidad", "grams": "Pesa (g)"}
        help_texts = {"note": "Por ejemplo: «huevo mediano», «sin hueso»."}
        widgets = {"grams": forms.NumberInput(attrs={"step": "any", "min": "0.001", "inputmode": "decimal"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].choices = [
            (u.value, "1 ml (se usa para todas las medidas de volumen)" if u == Unit.ML else f"1 {u.label}")
            for u in CONVERTIBLE_UNITS
        ]


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


class IngredientReviewForm(forms.Form):
    """What the label of the product this household buys says it contains."""

    traits = forms.MultipleChoiceField(
        label="Según la etiqueta, contiene", choices=Trait.choices, required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Marca también lo que aparezca como «puede contener trazas de…». Si no contiene "
        "ninguno, déjalo todo sin marcar.",
    )
    note = forms.CharField(label="Marca o nota (opcional)", max_length=120, required=False)
    confirm = forms.BooleanField(
        label="He leído la lista de ingredientes y alérgenos de la etiqueta del producto que compramos.",
        required=True, error_messages={"required": "Confirma que has leído la etiqueta."},
    )
