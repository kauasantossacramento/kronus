"""Kronus — settings de producao (Secao 9 do plano: Seguranca)."""
from decouple import config
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False

# ==============================================================
# Guardas de arranque
# ==============================================================
# Producao recusa subir com a chave de desenvolvimento. O `check
# --deploy` apenas avisa, e um aviso passa despercebido num pipeline
# de deploy: com a SECRET_KEY padrao, assinatura de sessao e token de
# reset de senha viram forjaveis por qualquer um que leia o repositorio.
SECRET_KEY = config("SECRET_KEY")
if SECRET_KEY.startswith("django-insecure-") or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "SECRET_KEY de producao ausente ou insegura. Gere uma com: "
        "python -c \"from django.core.management.utils import "
        "get_random_secret_key as g; print(g())\" "
        "e defina SECRET_KEY no ambiente."
    )

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="kronus.online,www.kronus.online",
    cast=lambda v: [h.strip() for h in v.split(",") if h.strip()],
)
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS com '*' em producao aceita qualquer Host, o que "
        "abre envenenamento de cabecalho Host em links de e-mail."
    )

# ==============================================================
# HTTPS obrigatorio
# ==============================================================
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# ==============================================================
# Cabecalhos de seguranca
# ==============================================================
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # necessario para HTMX ler o token

CSRF_TRUSTED_ORIGINS = [
    "https://kronus.online",
    "https://www.kronus.online",
]

# Content Security Policy aplicada via apps.core.middleware.SecurityHeadersMiddleware
CSP_DEFAULT_SRC = "'self'"
CSP_IMG_SRC = "'self' data: blob: https://kstec.online"
CSP_SCRIPT_SRC = "'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com"
CSP_STYLE_SRC = "'self' 'unsafe-inline' https://fonts.googleapis.com"
CSP_FONT_SRC = "'self' https://fonts.gstatic.com data:"
CSP_CONNECT_SRC = "'self' wss://kronus.online"

# ==============================================================
# Sentry
# ==============================================================
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:  # pragma: no cover
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment="production",
    )
