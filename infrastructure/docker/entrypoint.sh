#!/bin/sh
set -e

# Wait for PostgreSQL to accept connections before doing anything DB-related.
if [ -n "$DATABASE_URL" ]; then
  echo "Waiting for the database..."
  until python -c "import os,urllib.parse as u,psycopg2; d=u.urlparse(os.environ['DATABASE_URL']); psycopg2.connect(dbname=d.path[1:], user=d.username, password=d.password, host=d.hostname, port=d.port or 5432).close()" 2>/dev/null; do
    sleep 1
  done
  echo "Database is ready."
fi

# Only the web service runs migrations and collects static (set RUN_MIGRATIONS=1).
if [ "$RUN_MIGRATIONS" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
fi

exec "$@"
