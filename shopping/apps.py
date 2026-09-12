from django.apps import AppConfig


class ShoppingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shopping"

    def ready(self):
        from planning.signals import meals_changed

        from .services import recalculate_for_dates

        def on_meals_changed(sender, household, dates, **kwargs):
            recalculate_for_dates(household, dates)

        meals_changed.connect(on_meals_changed, dispatch_uid="shopping_recalculate_on_meals_changed", weak=False)
