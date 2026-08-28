"""Kronus — settings de desenvolvimento."""
from .base import *  # noqa: F401,F403
from .base import BASE_DIR, CSRF_TRUSTED_ORIGINS, INSTALLED_APPS  # noqa: F401

DEBUG = True

ALLOWED_HOSTS = ["*"]

# django-extensions e util em dev (shell_plus, graph_models, runserver_plus)
try:
    import django_extensions  # noqa: F401

    INSTALLED_APPS = INSTALLED_APPS + ["django_extensions"]
except ImportError:  # pragma: no cover
    pass

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Em dev servimos os arquivos estaticos sem manifest para nao exigir collectstatic
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

INTERNAL_IPS = ["127.0.0.1"]

# ==============================================================
# Intranet — teste do totem em dispositivo real
# ==============================================================
# O IP da maquina vem do DHCP e muda. Em vez de fixa-lo no .env e
# quebrar toda vez que o roteador reatribui, detectamos em tempo de
# carga e liberamos as origens correspondentes.
#
# `ALLOWED_HOSTS = ["*"]` acima ja cobre o acesso; o que realmente
# precisa do IP e o CSRF, que exige origem exata (esquema + host +
# porta) para aceitar POST vindo de fora de localhost.
try:
    from apps.core.utils import ips_locais

    _ips = ips_locais()
except Exception:  # pragma: no cover — nunca impedir o servidor de subir
    _ips = []

for _ip in _ips:
    for _porta in ("8000", "8443"):
        for _esquema in ("http", "https"):
            _origem = f"{_esquema}://{_ip}:{_porta}"
            if _origem not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(_origem)

#: IPs detectados, exibidos por `manage.py intranet`.
IPS_DETECTADOS = _ips
