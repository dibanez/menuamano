"""Access to personal health data (weight history).

Belonging to a household does not grant access. A user can see and record a diner's weight if
they are the diner's linked user or hold an explicit HealthDataAccess grant. Grants are managed
by the linked user; for diners without an account (e.g. children), by household admins.

Because the linked account controls that data, the link itself is protected: see
`linkable_accounts`.
"""

from households.models import Membership, Role

from .models import HealthDataAccess


def linkable_accounts(user, household, diner=None):
    """Accounts `user` may link to `diner` (None for a new diner), or None if they cannot change it.

    The link can never be moved to someone else: only the linked person can remove it, and only
    admins can link an existing diner. Anyone may link themselves to a diner they create.
    """
    from accounts.models import User

    taken = household.diners.exclude(linked_user=None)
    if diner is not None:
        taken = taken.exclude(pk=diner.pk)
    free = (
        User.objects.filter(memberships__household=household)
        .exclude(pk__in=taken.values("linked_user")).order_by("email")
    )
    if diner is not None and diner.linked_user_id:
        return free.filter(pk=user.pk) if diner.linked_user_id == user.pk else None
    if Membership.objects.filter(user=user, household=household, role=Role.ADMIN).exists():
        return free
    return free.filter(pk=user.pk) if diner is None else None


def can_view_health(user, diner):
    if not user.is_authenticated:
        return False
    if not Membership.objects.filter(user=user, household_id=diner.household_id).exists():
        return False
    if diner.linked_user_id == user.pk:
        return True
    return HealthDataAccess.objects.filter(diner=diner, user=user).exists()


def can_manage_health_access(user, diner):
    membership = Membership.objects.filter(user=user, household_id=diner.household_id).first()
    if membership is None:
        return False
    if diner.linked_user_id:
        return diner.linked_user_id == user.pk
    return membership.is_admin
