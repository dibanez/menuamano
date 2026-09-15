FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY . .

# The code stays read-only for the app user: it only writes the static files collected at startup.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/staticfiles && chown app:app /app/staticfiles
USER app

EXPOSE 8000

# Production default; compose.yaml overrides it with runserver for local development.
CMD ["sh", "-c", "python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 90"]
