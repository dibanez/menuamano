from config.env import env_bool

from .base import *  # noqa: F401,F403

DEBUG = env_bool("DJANGO_DEBUG", True)
# Containers reach the dev server through the published port; keep it permissive locally.
ALLOWED_HOSTS = ["*"]
