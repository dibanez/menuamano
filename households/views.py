from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from billing import entitlements
from core import throttle
from core.emails import send_email
from diners.models import HealthDataAccess

from . import invitations
from .forms import HouseholdForm, NewHouseholdForm
from .models import INVITATION_DAYS, Invitation, Membership, Role
from .permissions import SESSION_KEY, activate_household, household_required

NEW_LINK_SESSION_KEY = "new_invitation_link"
INVITATION_EMAILS_PER_DAY = 20


@login_required
def onboarding(request):
    form = NewHouseholdForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            household = form.save()
            Membership.objects.create(user=request.user, household=household, role=Role.ADMIN)
        request.session[SESSION_KEY] = household.pk
        messages.success(request, f"Hogar «{household.name}» creado. Añade ahora a quienes coméis en casa.")
        return redirect("diners:create")
    memberships = Membership.objects.filter(user=request.user).select_related("household")
    return render(request, "households/onboarding.html", {"form": form, "memberships": memberships})


@login_required
@require_POST
def switch(request):
    membership = activate_household(request, request.POST.get("household"))
    messages.info(request, f"Ahora estás en «{membership.household.name}».")
    return redirect("core:home")


@household_required(Role.ADMIN)
def settings_view(request):
    household = request.household
    form = HouseholdForm(request.POST or None, instance=household, prefix="h")
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Configuración guardada.")
        return redirect("households:settings")
    members = household.memberships.select_related("user").order_by("created_at")
    context = {
        "form": form,
        "members": members,
        "roles": Role.choices,
        "invitations": household.invitations.usable(),
        # The raw link is shown once, right after creating it; only its hash is stored.
        "new_link": request.session.pop(NEW_LINK_SESSION_KEY, None),
        "invitation_days": INVITATION_DAYS,
    }
    return render(request, "households/settings.html", context)


def _admins_left(household, excluding):
    return household.memberships.filter(role=Role.ADMIN).exclude(pk=excluding.pk).exists()


@household_required(Role.ADMIN)
@require_POST
def change_role(request, pk):
    member = get_object_or_404(Membership, pk=pk, household=request.household)
    role = request.POST.get("role")
    if role not in Role.values:
        messages.error(request, "Rol no válido.")
    elif member.role == Role.ADMIN and role != Role.ADMIN and not _admins_left(request.household, member):
        messages.error(request, "El hogar necesita al menos una persona administradora.")
    else:
        member.role = role
        member.save(update_fields=["role"])
        messages.success(request, "Rol actualizado.")
    return redirect("households:settings")


@household_required(Role.ADMIN)
@require_POST
def remove_member(request, pk):
    member = get_object_or_404(Membership, pk=pk, household=request.household)
    if member.role == Role.ADMIN and not _admins_left(request.household, member):
        messages.error(request, "No puedes quitar a la última persona administradora.")
    else:
        with transaction.atomic():
            # Their account stops controlling the household's diners, which pass to the admins,
            # and nobody keeps access to that health data until an admin grants it again.
            diners = request.household.diners.filter(linked_user=member.user)
            HealthDataAccess.objects.filter(diner__in=diners).delete()
            diners.update(linked_user=None)
            HealthDataAccess.objects.filter(diner__household=request.household, user=member.user).delete()
            member.delete()
        messages.success(request, "Miembro eliminado del hogar.")
    return redirect("households:settings")


# --- Invitation links -----------------------------------------------------------------------


@household_required(Role.ADMIN)
@require_POST
def invitation_create(request):
    role = request.POST.get("role")
    email = request.POST.get("email", "").strip().lower()
    if role not in Role.values:
        messages.error(request, "Elige un rol válido para la invitación.")
        return redirect("households:settings")
    if not entitlements.can_add_member(request.household):
        messages.error(request, entitlements.member_limit_message())
        return redirect("households:settings")
    if email:
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "El correo no es válido. Revísalo o deja el campo vacío para copiar el enlace.")
            return redirect("households:settings")
        if not throttle.allow(f"invite:household:{request.household.pk}", INVITATION_EMAILS_PER_DAY, timedelta(days=1)):
            messages.error(
                request, "Hoy ya se han enviado muchas invitaciones por correo desde este hogar. Crea el enlace "
                "sin correo y compártelo tú, o prueba mañana.",
            )
            return redirect("households:settings")
    invitation, token = Invitation.issue(request.household, role, request.user, email=email)
    link = request.build_absolute_uri(reverse("households:invitation", args=[token]))
    request.session[NEW_LINK_SESSION_KEY] = link
    if not email:
        messages.success(request, f"Invitación creada. Copia el enlace y compártelo: sirve una vez y caduca en {INVITATION_DAYS} días.")
    elif send_email(
        "invitation", email, "Te han invitado a un hogar en menuamano",
        {"household": request.household, "inviter": request.user, "role": invitation.get_role_display(),
         "link": link, "expires_at": invitation.expires_at},
    ):
        messages.success(request, f"Invitación enviada a {email}. También puedes copiar el enlace.")
    else:
        messages.warning(request, f"No se ha podido enviar el correo a {email}. Copia el enlace y compártelo tú.")
    return redirect("households:settings")


@household_required(Role.ADMIN)
@require_POST
def invitation_revoke(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk, household=request.household)
    invitation.revoked = True
    invitation.save(update_fields=["revoked"])
    messages.success(request, "Invitación anulada. El enlace ya no funciona.")
    return redirect("households:settings")


def invitation(request, token):
    invitation_obj = invitations.find(token)
    try:
        invitations.check_usable(invitation_obj)
    except invitations.InvitationError as exc:
        return render(request, "households/invitation.html", {"error": exc.message}, status=exc.status)

    if not request.user.is_authenticated:
        return render(request, "households/invitation.html", {"invitation": invitation_obj, "anonymous": True})

    if request.method == "POST":
        try:
            membership, created = invitations.accept(token, request.user)
        except invitations.InvitationError as exc:
            return render(request, "households/invitation.html", {"error": exc.message}, status=exc.status)
        request.session[SESSION_KEY] = membership.household_id
        if created:
            messages.success(request, f"Ya formas parte de «{membership.household.name}».")
        else:
            messages.info(request, f"Ya eras miembro de «{membership.household.name}»; tu rol no ha cambiado.")
        return redirect("core:home")

    already = Membership.objects.filter(user=request.user, household=invitation_obj.household).exists()
    return render(request, "households/invitation.html", {"invitation": invitation_obj, "already": already})
