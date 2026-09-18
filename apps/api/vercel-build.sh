#!/usr/bin/env sh
set -eu

# Vercel builds the function before it deploys it. Collecting static files here
# makes Django admin/static responses work without writing to the function at
# request time. Dummy local URLs are only fallbacks for a build that has not had
# runtime environment variables attached yet; no network connection is opened
# by collectstatic.
export DJANGO_SETTINGS_MODULE="plane.settings.production"
export PLANE_LOG_DIR="${PLANE_LOG_DIR:-/tmp/plane-logs}"
export DATABASE_URL="${DATABASE_URL:-postgresql://plane:plane@127.0.0.1:5432/plane}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/}"
export AMQP_URL="${AMQP_URL:-amqp://guest:guest@127.0.0.1:5672//}"

python manage.py collectstatic --noinput
