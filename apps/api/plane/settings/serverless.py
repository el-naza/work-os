"""Settings for short-lived serverless Django invocations.

Vercel can run Django's WSGI application, but it cannot keep a Celery worker,
WebSocket server, or local filesystem alive between requests. This module keeps
request/response API behavior compatible with production while making those
platform constraints explicit and safe by default.
"""

from __future__ import annotations

import os

# production.py constructs its logging configuration at import time.
os.environ.setdefault("PLANE_LOG_DIR", "/tmp/plane-logs")

from django.core.exceptions import ImproperlyConfigured

from .production import *  # noqa: F401,F403


SERVERLESS_MODE = True
DEBUG = False

# These values are evaluated during settings import. Keep the default log path
# writable on Vercel, where the deployed bundle is read-only.
PLANE_LOG_DIR = os.environ.setdefault("PLANE_LOG_DIR", "/tmp/plane-logs")
LOG_DIR = PLANE_LOG_DIR

# A pooled Postgres URL is strongly recommended for serverless traffic. Do not
# hold a Django connection open across invocations; the provider owns pooling.
for _database in DATABASES.values():
    _database["CONN_MAX_AGE"] = int(os.environ.get("DATABASE_CONN_MAX_AGE", "0"))
    _database["CONN_HEALTH_CHECKS"] = True

# Redis is used for sessions, throttling, magic-link state, and cache. Failing
# during cold start with a useful message is safer than accepting requests that
# later fail with an obscure cache error.
if not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL must be configured when using serverless settings")

# Celery workers and beat processes cannot run inside a Vercel request function.
# Inline execution is a compatibility fallback for small tasks (mail, activity,
# and bookkeeping). Set SERVERLESS_INLINE_TASKS=0 only when an external Celery
# worker and a real broker are available; long-running exports should not rely
# on the inline fallback.
SERVERLESS_INLINE_TASKS = os.environ.get("SERVERLESS_INLINE_TASKS", "1") == "1"
CELERY_TASK_ALWAYS_EAGER = SERVERLESS_INLINE_TASKS
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_STORE_EAGER_RESULT = False

# Redis is a practical broker fallback for a small deployment. An AMQP_URL or a
# dedicated CELERY_BROKER_URL still takes precedence when an external worker is
# added later.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or os.environ.get("AMQP_URL") or REDIS_URL
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL

# Keep read replicas disabled in the default serverless/free-tier topology. A
# replica adds another connection pool and should be introduced deliberately.
ENABLE_READ_REPLICA = False

# S3/R2 is mandatory for uploads because a serverless filesystem is ephemeral.
# The existing storage backend reads the AWS_* variables from the environment.
USE_MINIO = False
