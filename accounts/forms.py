from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm

from core.emails import send_email

from .models import User


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "display_name")
        labels = {"display_name": "¿Cómo quieres que te llamemos?"}

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return email


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs={"autofocus": True}))

    error_messages = {
        "invalid_login": "Correo o contraseña incorrectos.",
        "inactive": "Esta cuenta está desactivada.",
    }


class MenuPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Correo electrónico", max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email,
                  html_email_template_name=None):
        # Same page whether or not the address exists; send failures are only logged.
        send_email("password_reset", to_email, "Restablece tu contraseña de menuamano", context)
