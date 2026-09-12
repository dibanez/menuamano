"""Small helpers to read typed settings from environment variables."""

import os

from django.core.exceptions import ImproperlyConfigured


def env_str(name, default=None, required=False):
    value = os.environ.get(name)
    if value is None or value == "":
        if required:
            raise ImproperlyConfigured(f"Environment variable {name} is required")
        return default
    return value


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def env_float(name, default):
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def env_list(name, default=None):
    value = os.environ.get(name)
    if value is None or value == "":
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]
