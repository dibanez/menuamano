from django import forms

from .models import ReminderPreference


class ReminderForm(forms.ModelForm):
    class Meta:
        model = ReminderPreference
        fields = ("tomorrow", "hour", "week")

    def __init__(self, *args, can_plan=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_plan:
            del self.fields["week"]  # only people who plan can act on it
