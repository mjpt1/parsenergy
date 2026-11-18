from pathlib import Path
import os
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# The file log handler opens this at startup; make sure the directory exists so a
# fresh deployment (e.g. a fresh cPanel upload) doesn't 500 on the first request.
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me')
DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sites',
    'channels',
    'rest_framework',
    'rest_framework.authtoken',
    'drf_spectacular',
    'corsheaders',
    'django_filters',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'apps.core',
    'apps.accounts',
    'apps.plants',
    'apps.vpp',
    'apps.monitoring',
    'apps.alerts',
    'apps.analytics',
    'apps.reports',
    'apps.ml',
    'apps.api',
    'apps.pwa',
    'apps.requests',
    'apps.leads',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.api.middleware.IntegrationReadOnlyMiddleware',
    'apps.accounts.middleware.RoleRoutingMiddleware',
    'apps.core.middleware.NoStoreHTMLMiddleware',
    'apps.analytics.middleware.VisitTrackingMiddleware',
]

ROOT_URLCONF = 'solarops.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.context_processors.global_settings',
                'apps.core.context_processors.calendar_settings',
                'apps.core.context_processors.ai_flags',
                'apps.core.context_processors.nav_counts',
            ],
        },
    },
]

WSGI_APPLICATION = 'solarops.wsgi.application'
ASGI_APPLICATION = 'solarops.asgi.application'

# Database: use DATABASE_URL when provided (e.g. Postgres in Docker/production),
# otherwise fall back to local SQLite for development.
if env('DATABASE_URL', default=''):
    DATABASES = {'default': env.db('DATABASE_URL')}
    # The host's MariaDB drops idle connections after 180s (wait_timeout), so
    # keep reused connections well under that and test them before each request;
    # otherwise a stale one fails with "MySQL server has gone away" (HTTP 500).
    DATABASES['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=60)
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True
    # Strict mode: an invalid or too-long value raises an error instead of being
    # silently truncated or replaced in MariaDB.
    if 'mysql' in DATABASES['default']['ENGINE']:
        DATABASES['default'].setdefault('OPTIONS', {})['init_command'] = (
            "SET sql_mode='STRICT_TRANS_TABLES'")
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'fa'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

# Persian-only: no language switcher, LocaleMiddleware always resolves to fa.
LANGUAGES = [
    ('fa', 'فارسی'),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
# Contracts and receipts: never under MEDIA_ROOT, downloaded only through permission checks.
PRIVATE_MEDIA_ROOT = BASE_DIR / 'private_media'
# On hosts without a separate web server for uploads (e.g. cPanel/Passenger),
# set SERVE_MEDIA=True so Django itself serves /media/ (see urls.py).
SERVE_MEDIA = env.bool('SERVE_MEDIA', default=False)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'app.log'),
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SITE_ID = 1
AUTH_USER_MODEL = 'accounts.User'

# In development allow any origin; in production restrict to an explicit allowlist.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
CSRF_TRUSTED_ORIGINS = env.list(
    'CSRF_TRUSTED_ORIGINS',
    default=['http://127.0.0.1:8000', 'http://localhost:8000'],
)

# --- Production security hardening (active only when DEBUG is off) ---
if not DEBUG:
    # Honour the X-Forwarded-Proto header set by the Nginx reverse proxy.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        # Service accounts (username prefix `svc-`) are read-only on every
        # endpoint, enforced here rather than per view so a new viewset cannot
        # accidentally open a write path to an integration token.
        'apps.api.permissions.ReadOnlyForIntegrations',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': env('THROTTLE_ANON', default='60/min'),
        'user': env('THROTTLE_USER', default='600/min'),
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'SolarOps API',
    'DESCRIPTION': 'API for solar plant monitoring and management',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='no-reply@solarops.local')

REDIS_URL = env('REDIS_URL', default='redis://127.0.0.1:6379/0')

# Cache (and DRF throttle store): Redis in production, in-memory for local dev
# so the app runs without a Redis server.
if env.bool('USE_REDIS_CACHE', default=False):
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}}
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# Channels: Redis layer in production; in-memory for local dev (no Redis needed).
if env.bool('USE_REDIS_CHANNELS', default=False):
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# A CSRF failure here is nearly always an expired form, not an attack, so the
# visitor gets a Persian page with a retry button instead of Django's bare 403.
CSRF_FAILURE_VIEW = 'apps.core.views.csrf_failure'

# Slide the session forward on every request. Without this the two-week cookie
# is counted from login, so someone who uses the panel daily is still logged
# out mid-task a fortnight later — and that logout surfaces as a CSRF 403 on
# whatever form they happened to have open.
SESSION_SAVE_EVERY_REQUEST = True

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'
