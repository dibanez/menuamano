from django import forms

from foods.models import Category, Unit

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class NewListForm(forms.Form):
    start = forms.DateField(label="Desde", widget=DATE_WIDGET)
    end = forms.DateField(label="Hasta", widget=DATE_WIDGET)
    name = forms.CharField(label="Nombre (opcional)", max_length=80, required=False)

    MAX_DAYS = 62

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end:
            if end < start:
                raise forms.ValidationError("La fecha final debe ser igual o posterior a la inicial.")
            if (end - start).days >= self.MAX_DAYS:
                raise forms.ValidationError(f"Elige un intervalo de como mucho {self.MAX_DAYS} días.")
        return data


class ManualItemForm(forms.Form):
    name = forms.CharField(label="Artículo", max_length=100)
    quantity = forms.DecimalField(label="Cantidad", required=False, min_value=0, max_digits=10, decimal_places=3)
    unit = forms.ChoiceField(label="Unidad", required=False, choices=[("", "—")] + list(Unit.choices))
    category = forms.ChoiceField(label="Sección", choices=Category.choices, initial=Category.OTHER)
    note = forms.CharField(label="Nota", max_length=120, required=False)
