from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import invitations
from .forms import AddMemberForm, HouseholdForm, NewHouseholdForm
from .models import INVITATION_DAYS, Invitation, Membership, Role
from .permissions import SESSION_KEY, activate_household, household_required

NEW_LINK_SESSION_KEY = "new_invitation_link"


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
    member_form = AddMemberForm(household=household, prefix="m")
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Configuración guardada.")
        return redirect("households:settings")
    members = household.memberships.select_related("user").order_by("created_at")
    context = {
        "form": form,
        "member_form": member_form,
        "members": members,
        "roles": Role.choices,
        "invitations": household.invitations.usable(),
        # The raw link is shown once, right after creating it; only its hash is stored.
        "new_link": request.session.pop(NEW_LINK_SESSION_KEY, None),
        "invitation_days": INVITATION_DAYS,
    }
    return render(request, "households/settings.html", context)


@household_required(Role.ADMIN)
@require_POST
def add_member(request):
    form = AddMemberForm(request.POST, household=request.household, prefix="m")
    if form.is_valid():
        Membership.objects.create(user=form.user, household=request.household, role=form.cleaned_data["role"])
        messages.success(request, f"{form.user} ya forma parte del hogar.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("households:settings")


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
        member.delete()
        messages.success(request, "Miembro eliminado del hogar.")
    return redirect("households:settings")


# --- Invitation links -----------------------------------------------------------------------


@household_required(Role.ADMIN)
@require_POST
def invitation_create(request):
    role = request.POST.get("role")
    if role not in Role.values:
        messages.error(request, "Elige un rol válido para la invitación.")
        return redirect("households:settings")
    _, token = Invitation.issue(request.household, role, request.user)
    request.session[NEW_LINK_SESSION_KEY] = request.build_absolute_uri(reverse("households:invitation", args=[token]))
    messages.success(request, f"Invitación creada. Copia el enlace y compártelo: sirve una vez y caduca en {INVITATION_DAYS} días.")
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
