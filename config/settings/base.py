"""Settings shared by every environment. Environment-specific modules extend this one."""

from email.utils import getaddresses
from pathlib import Path

from config.env import env_float, env_int, env_list, env_str

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
# "console" prints emails to the logs (development); "mailgun" sends them through the Mailgun API.
EMAIL_BACKENDS = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "mailgun": "anymail.backends.mailgun.EmailBackend",
}
EMAIL_PROVIDER = env_str("EMAIL_PROVIDER", "console")
EMAIL_BACKEND = EMAIL_BACKENDS.get(EMAIL_PROVIDER, EMAIL_BACKENDS["console"])
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

# --- AI assistant -----------------------------------------------------------
# "demo" runs a deterministic local provider; "openai" calls the OpenAI API from the backend.
AI_PROVIDER = env_str("AI_PROVIDER", "demo")
OPENAI_API_KEY = env_str("OPENAI_API_KEY", "")
OPENAI_MODEL = env_str("OPENAI_MODEL", "")
OPENAI_TIMEOUT_SECONDS = env_float("OPENAI_TIMEOUT_SECONDS", 45.0)
OPENAI_MAX_RETRIES = env_int("OPENAI_MAX_RETRIES", 2)
OPENAI_MAX_OUTPUT_TOKENS = env_int("OPENAI_MAX_OUTPUT_TOKENS", 6000)

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
    },
}
