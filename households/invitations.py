from django.db import transaction
from django.utils import timezone

from billing import entitlements

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
        # An invitation sent to an address is for that person only; links without one are shareable.
        if invitation.email and invitation.email.lower() != user.email.lower():
            raise InvitationError(
                "Esta invitación es para otra dirección de correo. Entra con la cuenta de ese correo "
                "o pide un enlace nuevo.",
                status=403,
            )
        membership = Membership.objects.filter(user=user, household=invitation.household).first()
        if membership is not None:
            return membership, False  # the link stays usable for someone else
        if not entitlements.can_add_member(invitation.household):
            raise InvitationError(
                "Este hogar ya tiene el máximo de personas con cuenta. "
                "Pide a quien te invitó que libere un hueco.",
                status=409,
            )
        membership = Membership.objects.create(user=user, household=invitation.household, role=invitation.role)
        invitation.accepted_by = user
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_by", "accepted_at"])
        return membership, True
