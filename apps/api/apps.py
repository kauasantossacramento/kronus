from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.api"
    verbose_name = "API REST"

    def ready(self):
        # Registra os esquemas de seguranca do OpenAPI. O import precisa
        # acontecer no boot: o drf-spectacular so enxerga extensoes ja
        # importadas quando gera o schema.
        from apps.api import schema  # noqa: F401
