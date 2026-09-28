#!/bin/sh
# Production entrypoint (Docker / Render). Safe to run on every boot:
#   1. apply Alembic migrations (idempotent)
#   2. optionally load demo data — ONLY into an empty database (never wipes existing data)
#   3. start uvicorn on $PORT (hosting providers assign it), bound to 0.0.0.0, trusting proxy headers
set -e
cd "$(dirname "$0")/.."

echo "[start] applying database migrations"
alembic upgrade head

case "${SEED_DEMO_DATA:-false}" in
  true|1|yes) echo "[start] SEED_DEMO_DATA=true -> seeding if the database is empty"; python -m scripts.seed ;;
esac

echo "[start] starting API on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" --timeout-keep-alive 75
