from django import forms

from core.choices import MealType
from diners.models import Diner

from .models import DateException, Meal, MealMode, RecurringRule

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class MealDetailsForm(forms.ModelForm):
    """Mode, notes and what was eaten. The lock has its own button at the top of the meal page."""

    class Meta:
        model = Meal
        fields = ("mode", "notes", "outcome", "outcome_notes")
        widgets = {
            "mode": forms.RadioSelect,
            "outcome": forms.RadioSelect,
            "notes": forms.Textarea(attrs={"rows": 2, "placeholder": "Por ejemplo: cumpleaños, cenamos antes…"}),
            "outcome_notes": forms.TextInput(attrs={"placeholder": "Detalle (opcional): qué se comió en su lugar"}),
        }


class MoveForm(forms.Form):
    action = forms.ChoiceField(
        label="Qué hacer", choices=[("move", "Mover"), ("copy", "Copiar")], initial="move", widget=forms.RadioSelect,
    )
    target_date = forms.DateField(label="Día", widget=DATE_WIDGET)
    target_type = forms.ChoiceField(label="Comida", widget=forms.RadioSelect)
    overwrite = forms.BooleanField(label="Sustituir si ya hay algo planificado", required=False)

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_type"].choices = [(mt, MealType(mt).label) for mt in household.meal_types]


class RangeForm(forms.Form):
    start = forms.DateField(label="Desde", widget=DATE_WIDGET)
    end = forms.DateField(label="Hasta", widget=DATE_WIDGET)

    MAX_DAYS = 62

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end:
            if end < start:
                raise forms.ValidationError("La fecha final debe ser posterior a la inicial.")
            if (end - start).days >= self.MAX_DAYS:
                raise forms.ValidationError(f"Elige un intervalo de como mucho {self.MAX_DAYS} días.")
        return data


class RuleForm(forms.ModelForm):
    class Meta:
        model = RecurringRule
        fields = ("weekday", "meal_type", "mode", "notes", "valid_from", "valid_until")
        widgets = {"valid_from": DATE_WIDGET, "valid_until": DATE_WIDGET}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["meal_type"].choices = [(mt, MealType(mt).label) for mt in household.meal_types]


class ExceptionForm(forms.ModelForm):
    class Meta:
        model = DateException
        fields = ("date", "meal_type", "mode", "override_attendance", "attendees", "notes")
        widgets = {"date": DATE_WIDGET, "attendees": forms.CheckboxSelectMultiple}
        help_texts = {"override_attendance": "Si lo marcas, solo asistirán las personas elegidas."}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["meal_type"].choices = [(mt, MealType(mt).label) for mt in household.meal_types]
        self.fields["mode"].choices = [("", "Sin cambiar la modalidad")] + list(MealMode.choices)
        self.fields["attendees"].queryset = Diner.objects.filter(household=household, is_active=True)
