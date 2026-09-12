from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-only-secret-key"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Tests never reach the paid API: the demo provider is the default and the key is blank.
AI_PROVIDER = "demo"
OPENAI_API_KEY = ""
OPENAI_MODEL = "test-model"

# Emails stay in memory (django.core.mail.outbox); webhooks use a fixed signing key.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "menuamano <no-reply@example.com>"
ANYMAIL = {
    "MAILGUN_API_KEY": "test-api-key",
    "MAILGUN_SENDER_DOMAIN": "mg.example.com",
    "MAILGUN_WEBHOOK_SIGNING_KEY": "test-signing-key",
}
