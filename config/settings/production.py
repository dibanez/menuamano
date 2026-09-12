from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int, env_list, env_str

from .base import *  # noqa: F401,F403
from .base import ANYMAIL, EMAIL_BACKENDS

DEBUG = False
SECRET_KEY = env_str("DJANGO_SECRET_KEY", required=True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 3600)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Email: Mailgun by default. Missing credentials stop the deployment instead of losing emails.
EMAIL_PROVIDER = env_str("EMAIL_PROVIDER", "mailgun")
if EMAIL_PROVIDER not in EMAIL_BACKENDS:
    raise ImproperlyConfigured(f"Unknown EMAIL_PROVIDER {EMAIL_PROVIDER!r}; use 'mailgun' or 'console'")
EMAIL_BACKEND = EMAIL_BACKENDS[EMAIL_PROVIDER]
# Billing: on by default. Without Stripe every household would get paid features for free.
BILLING_ENABLED = env_bool("BILLING_ENABLED", True)
if BILLING_ENABLED:
    STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY", required=True)
    STRIPE_WEBHOOK_SECRET = env_str("STRIPE_WEBHOOK_SECRET", required=True)
    STRIPE_PRICE_MONTHLY = env_str("STRIPE_PRICE_MONTHLY", required=True)
    STRIPE_PRICE_YEARLY = env_str("STRIPE_PRICE_YEARLY", required=True)

if EMAIL_PROVIDER == "mailgun":
    ANYMAIL["MAILGUN_API_KEY"] = env_str("MAILGUN_API_KEY", required=True)
    ANYMAIL["MAILGUN_SENDER_DOMAIN"] = env_str("MAILGUN_SENDER_DOMAIN", required=True)
    DEFAULT_FROM_EMAIL = env_str("DEFAULT_FROM_EMAIL", required=True)
    SERVER_EMAIL = env_str("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
