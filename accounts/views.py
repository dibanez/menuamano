from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import LoginForm, SignupForm


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
