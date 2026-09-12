"""Settings shared by every environment. Environment-specific modules extend this one."""

from email.utils import getaddresses
from pathlib import Path

from config.env import env_bool, env_float, env_int, env_list, env_str

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = env_str("DJANGO_SECRET_KEY", "insecure-development-key")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_htmx",
    "anymail",
    "core",
    "accounts",
    "households",
    "foods",
    "diners",
    "recipes",
    "planning",
    "shopping",
    "assistant",
    "billing",
]

MIDDLEWARE = [
    "core.middleware.HealthCheckMiddleware",  # first: health probes skip host checks and redirects
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "households.middleware.ActiveHouseholdMiddleware",
    "core.middleware.LegalConsentMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "households.context_processors.household",
                "assistant.context_processors.ai_mode",
                "billing.context_processors.billing",
                "core.context_processors.analytics",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("POSTGRES_DB", "menuamano"),
        "USER": env_str("POSTGRES_USER", "menuamano"),
        "PASSWORD": env_str("POSTGRES_PASSWORD", "menuamano"),
        "HOST": env_str("POSTGRES_HOST", "localhost"),
        "PORT": env_str("POSTGRES_PORT", "5433"),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        # Never wrap whole requests in a transaction: AI calls must stay outside of them.
        "ATOMIC_REQUESTS": False,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "es"
LANGUAGES = [("es", "Español")]
TIME_ZONE = "Europe/Madrid"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# --- Email ------------------------------------------------------------------
# "console" prints emails to the logs (development); "smtp" sends them through an SMTP server
# (Mailgun SMTP by default); "mailgun" sends them through the Mailgun HTTP API.
EMAIL_BACKENDS = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
    "mailgun": "anymail.backends.mailgun.EmailBackend",
}
EMAIL_PROVIDER = env_str("EMAIL_PROVIDER", "console")
EMAIL_BACKEND = EMAIL_BACKENDS.get(EMAIL_PROVIDER, EMAIL_BACKENDS["console"])
# SMTP. Mailgun: smtp.mailgun.org (EU accounts: smtp.eu.mailgun.org), port 587 with STARTTLS,
# or 465 with implicit TLS. The user and password are the domain's SMTP credentials.
EMAIL_HOST = env_str("EMAIL_HOST", "smtp.mailgun.org")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env_str("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_str("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", not EMAIL_USE_SSL)
EMAIL_TIMEOUT = env_float("EMAIL_TIMEOUT_SECONDS", 15.0)
DEFAULT_FROM_EMAIL = env_str("DEFAULT_FROM_EMAIL", "menuamano <no-reply@localhost>")
SERVER_EMAIL = env_str("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = "[menuamano] "
# Server error reports (DEBUG=False). Format: "Name <email>, other@example.com".
ADMINS = [(name or address, address) for name, address in getaddresses(env_list("DJANGO_ADMINS")) if address]
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # reset links expire after one day

ANYMAIL = {
    key: value
    for key, value in {
        "MAILGUN_API_KEY": env_str("MAILGUN_API_KEY", ""),
        "MAILGUN_SENDER_DOMAIN": env_str("MAILGUN_SENDER_DOMAIN", ""),
        # EU accounts: https://api.eu.mailgun.net/v3
        "MAILGUN_API_URL": env_str("MAILGUN_API_URL", "https://api.mailgun.net/v3"),
        "MAILGUN_WEBHOOK_SIGNING_KEY": env_str("MAILGUN_WEBHOOK_SIGNING_KEY", ""),
        "WEBHOOK_SECRET": env_str("ANYMAIL_WEBHOOK_SECRET", ""),
        "REQUESTS_TIMEOUT": env_float("EMAIL_TIMEOUT_SECONDS", 15.0),
    }.items()
    if value not in ("", None)
}

# Public base URL, for absolute links in emails sent outside a request (e.g. from webhooks).
SITE_URL = env_str("SITE_URL", "")

# --- Legal texts --------------------------------------------------------------
# Owner details for the legal notice and privacy policy (LSSI-CE art. 10, GDPR art. 13).
LEGAL_OWNER_NAME = env_str("LEGAL_OWNER_NAME", "")
LEGAL_OWNER_TAX_ID = env_str("LEGAL_OWNER_TAX_ID", "")
LEGAL_OWNER_ADDRESS = env_str("LEGAL_OWNER_ADDRESS", "")
LEGAL_CONTACT_EMAIL = env_str("LEGAL_CONTACT_EMAIL", "")
LEGAL_REGISTRY = env_str("LEGAL_REGISTRY", "")  # companies only, e.g. "Registro Mercantil de …"
LEGAL_HOSTING_PROVIDER = env_str("LEGAL_HOSTING_PROVIDER", "")

# --- Analytics (Google Tag Manager) -----------------------------------------
# Empty = not loaded (local development and tests).
GTM_CONTAINER_ID = env_str("GTM_CONTAINER_ID", "")
# "public": only for visitors who are not signed in (the app shows names and health data);
# "all": every page.
GTM_SCOPE = env_str("GTM_SCOPE", "public")
# Own consent banner (Consent Mode v2). Disable it if a CMP is configured inside GTM.
COOKIE_CONSENT_BANNER = env_bool("COOKIE_CONSENT_BANNER", True)

# --- Billing (Stripe) -------------------------------------------------------
STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = env_str("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY = env_str("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_YEARLY = env_str("STRIPE_PRICE_YEARLY", "")
STRIPE_AUTOMATIC_TAX = env_bool("STRIPE_AUTOMATIC_TAX", False)
# Without billing (local development) every household gets Premium features.
BILLING_ENABLED = env_bool("BILLING_ENABLED", bool(STRIPE_SECRET_KEY))
FREE_MAX_MEMBERS = env_int("FREE_MAX_MEMBERS", 2)
PREMIUM_MAX_MEMBERS = env_int("PREMIUM_MAX_MEMBERS", 8)
PREMIUM_AI_MONTHLY_LIMIT = env_int("PREMIUM_AI_MONTHLY_LIMIT", 150)
PREMIUM_PRICE_MONTHLY_LABEL = env_str("PREMIUM_PRICE_MONTHLY_LABEL", "4,99 €")
PREMIUM_PRICE_YEARLY_LABEL = env_str("PREMIUM_PRICE_YEARLY_LABEL", "49 €")

# --- AI assistant -----------------------------------------------------------
# "demo" runs a deterministic local provider; "openai" calls the OpenAI API from the backend.
AI_PROVIDER = env_str("AI_PROVIDER", "demo")
OPENAI_API_KEY = env_str("OPENAI_API_KEY", "")
OPENAI_MODEL = env_str("OPENAI_MODEL", "")
OPENAI_TIMEOUT_SECONDS = env_float("OPENAI_TIMEOUT_SECONDS", 45.0)
OPENAI_MAX_RETRIES = env_int("OPENAI_MAX_RETRIES", 2)
# Reasoning tokens count against the output budget: keep effort low and the budget roomy.
OPENAI_MAX_OUTPUT_TOKENS = env_int("OPENAI_MAX_OUTPUT_TOKENS", 16000)
# none, low, medium, high… Empty = do not send the parameter (for models without reasoning).
OPENAI_REASONING_EFFORT = env_str("OPENAI_REASONING_EFFORT", "low")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # The SDK may log request details at DEBUG; keep it quiet.
        "openai": {"level": "WARNING"},
        "httpx2": {"level": "WARNING"},
        # The email webhook URL is public and Mailgun retries for hours: log rejected calls,
        # never email them to DJANGO_ADMINS.
        "django.security.AnymailWebhookValidationFailure": {
            "handlers": ["console"], "level": "WARNING", "propagate": False,
        },
    },
}
