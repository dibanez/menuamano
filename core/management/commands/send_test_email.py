from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.emails import send_email


class Command(BaseCommand):
    help = "Send a test email to check the email provider configuration (e.g. Mailgun in production)."

    def add_arguments(self, parser):
        parser.add_argument("to", help="Recipient address")

    def handle(self, *args, to, **options):
        self.stdout.write(f"Backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"From: {settings.DEFAULT_FROM_EMAIL}")
        if not send_email("test", to, "Correo de prueba de menuamano", {"backend": settings.EMAIL_BACKEND}):
            raise CommandError("The email could not be sent. Check the logs and the MAILGUN_* variables.")
        self.stdout.write(self.style.SUCCESS(f"Test email accepted by the provider for {to}."))
