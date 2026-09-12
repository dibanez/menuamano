from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Person who signs in. Identified by email; `username` is not used."""

    username = None
    email = models.EmailField("correo electrónico", unique=True)
    display_name = models.CharField("nombre visible", max_length=80, blank=True)
    # Consent records (GDPR): when the terms/privacy and the explicit health-data consent were given,
    # and which version of the legal texts was accepted.
    terms_accepted_at = models.DateTimeField("condiciones aceptadas", null=True, blank=True)
    health_consent_at = models.DateTimeField("consentimiento de datos de salud", null=True, blank=True)
    legal_version = models.CharField("versión de los textos legales aceptada", max_length=20, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.display_name or self.email

    @property
    def short_name(self):
        return self.display_name or self.email.split("@")[0]
