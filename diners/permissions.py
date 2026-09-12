"""Access to personal health data (weight history).

Belonging to a household does not grant access. A user can see a diner's weight if they are
the diner's linked user or hold an explicit HealthDataAccess grant. Grants are managed by the
linked user; for diners without an account (e.g. children), by household admins.
"""

from households.models import Membership

from .models import HealthDataAccess


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
