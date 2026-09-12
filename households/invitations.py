from django.db import transaction
from django.utils import timezone

from .models import Invitation, Membership, hash_token


class InvitationError(Exception):
    def __init__(self, message, status=410):
        self.message = message
        self.status = status
        super().__init__(message)


def find(token):
    return Invitation.objects.select_related("household").filter(token_hash=hash_token(token)).first()


def check_usable(invitation):
    if invitation is None:
        raise InvitationError("El enlace de invitación no es válido.", status=404)
    if invitation.revoked:
        raise InvitationError("Esta invitación se ha anulado. Pide un enlace nuevo.")
    if invitation.accepted_at is not None:
        raise InvitationError("Esta invitación ya se ha usado. Pide un enlace nuevo.")
    if invitation.expires_at <= timezone.now():
        raise InvitationError("La invitación ha caducado. Pide un enlace nuevo.")


def accept(token, user):
    """Join the household. Returns (membership, created). Existing members keep their role."""
    with transaction.atomic():
        invitation = (
            Invitation.objects.select_for_update().select_related("household").filter(token_hash=hash_token(token)).first()
        )
        check_usable(invitation)
        membership = Membership.objects.filter(user=user, household=invitation.household).first()
        if membership is not None:
            return membership, False  # the link stays usable for someone else
        membership = Membership.objects.create(user=user, household=invitation.household, role=invitation.role)
        invitation.accepted_by = user
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_by", "accepted_at"])
        return membership, True
