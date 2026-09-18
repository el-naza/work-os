#!/usr/bin/env sh
set -eu

# Use Neon/Supabase's direct (unpooled) connection for migrations. The pooled
# DATABASE_URL is still the right value for request-time serverless traffic.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-plane.settings.production}"
export DATABASE_URL="${DIRECT_DATABASE_URL:-${DATABASE_URL:?Set DIRECT_DATABASE_URL or DATABASE_URL}}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/}"
export AMQP_URL="${AMQP_URL:-amqp://guest:guest@127.0.0.1:5672//}"
export PLANE_LOG_DIR="${PLANE_LOG_DIR:-/tmp/plane-logs}"

python manage.py migrate --noinput
