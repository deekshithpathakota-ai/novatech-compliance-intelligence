FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user; uploaded documents go to ./storage (ephemeral on Render — the text lives in Postgres).
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/storage \
    && chmod +x scripts/start.sh \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'), timeout=4)" || exit 1

# Migrations run on every boot (idempotent). Demo data is seeded only when SEED_DEMO_DATA=true AND the DB is empty.
CMD ["sh", "scripts/start.sh"]
