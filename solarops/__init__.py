# Use PyMySQL as the MySQLdb driver when MySQL is configured (cPanel shared
# hosting often can't build mysqlclient). Harmless when MySQL/PyMySQL is absent.
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:  # pragma: no cover - only needed for a MySQL deployment
    pass

# Celery is optional: on shared hosting (e.g. cPanel) there is usually no worker
# and the package may not be installed. The app must still boot without it.
try:
    from .celery import app as celery_app
except ImportError:  # pragma: no cover - depends on the deployment environment
    celery_app = None

__all__ = ('celery_app',)
