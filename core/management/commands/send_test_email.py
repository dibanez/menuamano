from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.emails import send_email


class Command(BaseCommand):
    help = "Send a test email to check the email provider configuration (e.g. Mailgun SMTP in production)."

    def add_arguments(self, parser):
        parser.add_argument("to", help="Recipient address")

    def handle(self, *args, to, **options):
        self.stdout.write(f"Backend: {settings.EMAIL_BACKEND}")
        if settings.EMAIL_BACKEND.endswith("smtp.EmailBackend"):
            security = "SSL" if settings.EMAIL_USE_SSL else "STARTTLS" if settings.EMAIL_USE_TLS else "none"
            self.stdout.write(f"SMTP: {settings.EMAIL_HOST}:{settings.EMAIL_PORT} ({security}), user {settings.EMAIL_HOST_USER}")
        self.stdout.write(f"From: {settings.DEFAULT_FROM_EMAIL}")
        if not send_email("test", to, "Correo de prueba de menuamano", {"backend": settings.EMAIL_BACKEND}):
            raise CommandError("The email could not be sent. Check the logs and the EMAIL_* (SMTP) or MAILGUN_* variables.")
        self.stdout.write(self.style.SUCCESS(f"Test email accepted by the provider for {to}."))
