"""Vercel entry point for Plane's Django API.

This module intentionally exposes both ``app`` and ``application``. Vercel's
Python runtime can discover either a WSGI callable named ``app`` or the Django
convention named ``application``.

The API remains a normal Django application. The adapter only makes the WSGI
boundary safe for short-lived serverless invocations; it does not turn Celery,
WebSockets, local files, or database connections into persistent services.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable


# Vercel runs this file as the function entry point. Add the Django project
# directory to sys.path without relying on the current working directory.
API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# /tmp is the writable filesystem in a serverless invocation. The production
# settings module uses this for its rotating file handler; request logs still go
# to stdout/stderr through the console handler and should be collected by the
# platform.
os.environ.setdefault("PLANE_LOG_DIR", "/tmp/plane-logs")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.serverless")

from django.core.wsgi import get_wsgi_application  # noqa: E402
from django.db import close_old_connections  # noqa: E402


_django_application = get_wsgi_application()


def app(environ: dict, start_response: Callable):
    """Serve one WSGI request and release stale database connections.

    A warm Vercel instance may handle requests from different users. Closing
    old connections at both ends of an invocation avoids leaking an expired
    serverless database connection into the next request.
    """

    close_old_connections()
    try:
        return _django_application(environ, start_response)
    finally:
        close_old_connections()


# Django and most WSGI tooling use this conventional name.
application = app
