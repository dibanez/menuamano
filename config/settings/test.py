from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-only-secret-key"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Tests never reach the paid API: the demo provider is the default and the key is blank.
AI_PROVIDER = "demo"
OPENAI_API_KEY = ""
OPENAI_MODEL = "test-model"
