from django.apps import AppConfig


class RhConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rh"
    verbose_name = "Painel RH"

    def ready(self):
        from apps.rh import signals  # noqa: F401
