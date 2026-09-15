import threading

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from core.emails import send_email
from core.legal import LEGAL_VERSION

from .models import User

TERMS_LABEL = "Tengo 14 años o más y acepto las condiciones de uso y la política de privacidad."
HEALTH_LABEL = (
    "Consiento de forma explícita que menuamano trate los datos de salud que registre (alergias, "
    "intolerancias, dietas, diabetes y, si lo uso, el peso) para planificar las comidas, y declaro que tengo "
    "el permiso de las personas cuyos datos introduzca o que soy su representante legal."
)


def add_consent_fields(form):
    form.fields["accept_terms"] = forms.BooleanField(
        label=TERMS_LABEL, required=True,
        error_messages={"required": "Tienes que aceptar las condiciones y la política de privacidad."},
        help_text=format_html(
            'Lee las <a href="{}" target="_blank" rel="noopener">condiciones</a> y la '
            '<a href="{}" target="_blank" rel="noopener">política de privacidad</a>.',
            reverse("core:legal_page", args=["condiciones"]), reverse("core:legal_page", args=["privacidad"]),
        ),
    )
    form.fields["health_consent"] = forms.BooleanField(
        label=HEALTH_LABEL, required=True,
        error_messages={"required": "Sin este consentimiento no podemos guardar alergias ni restricciones, que son la base del servicio."},
        help_text="Puedes retirarlo cuando quieras escribiéndonos; entonces borraremos esos datos.",
    )


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "display_name")
        labels = {"display_name": "¿Cómo quieres que te llamemos?"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_consent_fields(self)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        now = timezone.now()
        user.terms_accepted_at = user.health_consent_at = now
        user.legal_version = LEGAL_VERSION
        if commit:
            user.save()
        return user


class LegalConsentForm(forms.Form):
    """Shown to existing people when they have not accepted the current legal texts."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_consent_fields(self)


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
        # Same page whether or not the address exists; send failures are only logged. In the
        # background, sending does not make the answer slower when the account exists.
        args = ("password_reset", to_email, "Restablece tu contraseña de menuamano", context)
        if settings.EMAIL_IN_BACKGROUND:
            threading.Thread(target=send_email, args=args, daemon=True).start()
        else:
            send_email(*args)
