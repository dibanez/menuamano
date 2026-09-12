from django import forms

from accounts.models import User
from core.choices import MealType

from .models import Household, Membership, Role


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


class AddMemberForm(forms.Form):
    email = forms.EmailField(label="Correo de la persona", help_text="Debe haberse registrado antes en menuamano.")
    role = forms.ChoiceField(label="Rol", choices=Role.choices, initial=Role.EDITOR)

    def __init__(self, *args, household=None, **kwargs):
        self.household = household
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise forms.ValidationError("No hay ninguna cuenta con ese correo. Pídele que se registre primero.")
        if Membership.objects.filter(household=self.household, user=user).exists():
            raise forms.ValidationError("Esa persona ya es miembro del hogar.")
        self.user = user
        return email
