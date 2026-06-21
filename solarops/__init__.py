# Celery is optional: on shared hosting (e.g. cPanel) there is usually no worker
# and the package may not be installed. The app must still boot without it.
try:
    from .celery import app as celery_app
except ImportError:  # pragma: no cover - depends on the deployment environment
    celery_app = None

__all__ = ('celery_app',)
