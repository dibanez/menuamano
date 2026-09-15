"""Household scoping and role checks.

The active household id lives in the session only as a *preference*: it is revalidated
against `Membership` on every request, so a tampered id never grants access.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import Membership, Role

SESSION_KEY = "active_household_id"

ROLE_RANK = {Role.READER: 0, Role.EDITOR: 1, Role.ADMIN: 2}


def resolve_membership(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    memberships = Membership.objects.select_related("household").filter(user=user)
    wanted = request.session.get(SESSION_KEY)
    membership = memberships.filter(household_id=wanted).first() if wanted else None
    if membership is None:
        membership = memberships.order_by("created_at", "id").first()
        if membership is not None:
            request.session[SESSION_KEY] = membership.household_id
        else:
            request.session.pop(SESSION_KEY, None)
    return membership


def activate_household(request, household_id):
    """Switch the active household if (and only if) the user belongs to it."""
    try:
        household_id = int(household_id)
    except (TypeError, ValueError):
        raise PermissionDenied("Not a member of this household") from None
    membership = Membership.objects.filter(user=request.user, household_id=household_id).first()
    if membership is None:
        raise PermissionDenied("Not a member of this household")
    request.session[SESSION_KEY] = membership.household_id
    return membership


def has_role(membership, role):
    return membership is not None and ROLE_RANK[membership.role] >= ROLE_RANK[Role(role)]


def household_required(role=Role.READER):
    """Require login, an active household and at least `role` in it."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            membership = getattr(request, "membership", None)
            if membership is None:
                return redirect("households:onboarding")
            if not has_role(membership, role):
                raise PermissionDenied("Insufficient role in household")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
