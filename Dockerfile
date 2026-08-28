# ══════════════════════════════════════════════════════════════
# Kronus — imagem de aplicação (Django + Celery + Daphne)
# ══════════════════════════════════════════════════════════════
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

# Dependências de sistema:
#  - libpq-dev / gcc ............ psycopg2
#  - libcairo2 / libpango ....... WeasyPrint (espelho de ponto, comprovantes)
#  - libgl1 / libglib2.0-0 ...... OpenCV (reconhecimento facial)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-base.txt ./
RUN pip install --upgrade pip && pip install -r requirements-base.txt

COPY . .

RUN python manage.py collectstatic --noinput --settings=config.settings.development || true

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
