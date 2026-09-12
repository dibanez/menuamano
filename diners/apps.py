from django.apps import AppConfig


class DinersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "diners"

    def ready(self):
        from . import signals  # noqa: F401
