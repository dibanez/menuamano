from django.contrib import messages
from django.contrib.auth import login, views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme

from core.emails import send_email
from core.legal import needs_consent, record_consent

from .forms import LegalConsentForm, LoginForm, MenuPasswordResetForm, SignupForm


class MenuLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class MenuLogoutView(LogoutView):
    pass


def _safe_next(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return ""


def signup(request):
    next_url = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(next_url or "core:home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        if next_url:
            messages.success(request, "Cuenta creada.")
            return redirect(next_url)
        messages.success(request, "Cuenta creada. Ahora crea tu hogar.")
        return redirect("households:onboarding")
    return render(request, "accounts/signup.html", {"form": form, "next": next_url})


@login_required
def legal_consent(request):
    next_url = _safe_next(request) or reverse("core:home")
    if not needs_consent(request.user):
        return redirect(next_url)
    form = LegalConsentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        record_consent(request.user)
        messages.success(request, "Gracias. Ya puedes seguir usando menuamano.")
        return redirect(next_url)
    return render(request, "accounts/legal_consent.html", {"form": form, "next": next_url})


# --- Passwords ------------------------------------------------------------------------------


def notify_password_changed(request, user):
    """Security notice so people notice a change they did not make."""
    send_email(
        "password_changed", user.email, "Tu contraseña de menuamano ha cambiado",
        {"user": user, "reset_url": request.build_absolute_uri(reverse("accounts:password_reset"))},
    )


class MenuPasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = MenuPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")


class MenuPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class MenuPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        notify_password_changed(self.request, form.user)
        return response


class MenuPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


class MenuPasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("core:home")

    def form_valid(self, form):
        response = super().form_valid(form)
        notify_password_changed(self.request, form.user)
        messages.success(self.request, "Contraseña cambiada. Te hemos enviado un aviso por correo.")
        return response
