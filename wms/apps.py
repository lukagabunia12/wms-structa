from django.apps import AppConfig


class WmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wms"
    verbose_name = "WMS"

    def ready(self):
        # Branche le compteur d'échecs de connexion sur le signal de Django.
        from . import connexion  # noqa: F401
