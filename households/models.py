import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from core.choices import MealType, default_meal_types, sort_meal_types

INVITATION_DAYS = 7


class Household(models.Model):
    name = models.CharField("nombre", max_length=80)
    enabled_meal_types = ArrayField(
        models.CharField(max_length=16, choices=MealType.choices),
        default=default_meal_types,
        verbose_name="tipos de comida activos",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "hogar"
        verbose_name_plural = "hogares"

    def __str__(self):
        return self.name

    @property
    def meal_types(self):
        """Enabled meal types in canonical day order."""
        return sort_meal_types(self.enabled_meal_types)


class Role(models.TextChoices):
    ADMIN = "admin", "Administrador"
    EDITOR = "editor", "Editor"
    READER = "reader", "Lector"


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField("rol", max_length=10, choices=Role.choices, default=Role.READER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "miembro"
        verbose_name_plural = "miembros"
        constraints = [models.UniqueConstraint(fields=["user", "household"], name="unique_membership")]

    def __str__(self):
        return f"{self.user} @ {self.household} ({self.role})"

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def can_edit(self):
        return self.role in (Role.ADMIN, Role.EDITOR)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class InvitationQuerySet(models.QuerySet):
    def usable(self):
        return self.filter(revoked=False, accepted_at__isnull=True, expires_at__gt=timezone.now())


class Invitation(models.Model):
    """Single-use, expiring link to join a household. Only the token hash is stored."""

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="invitations")
    role = models.CharField("rol", max_length=10, choices=Role.choices, default=Role.EDITOR)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def issue(cls, household, role, user, days=INVITATION_DAYS):
        """Create an invitation and return it with the raw token (never stored)."""
        token = secrets.token_urlsafe(32)
        invitation = cls.objects.create(
            household=household, role=role, created_by=user, token_hash=hash_token(token),
            expires_at=timezone.now() + timedelta(days=days),
        )
        return invitation, token

    @property
    def is_usable(self):
        return not self.revoked and self.accepted_at is None and self.expires_at > timezone.now()
