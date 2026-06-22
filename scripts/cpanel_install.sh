#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$APP_DIR"

if [ ! -f manage.py ]; then
  echo "manage.py not found. Run this script from the SolarOps app root." >&2
  exit 1
fi

mkdir -p logs tmp media staticfiles

if [ ! -f .env ]; then
  cp .env.cpanel.example .env
  python - <<'PY'
from pathlib import Path
import secrets

path = Path('.env')
text = path.read_text(encoding='utf-8')
text = text.replace('PUT-A-LONG-RANDOM-VALUE-HERE', secrets.token_urlsafe(50))
path.write_text(text, encoding='utf-8')
print('Created .env with a generated SECRET_KEY. Edit ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS before first public use.')
PY
else
  echo ".env already exists; leaving it unchanged."
fi

python -m pip install --upgrade pip
python -m pip install -r requirements-cpanel.txt

python manage.py migrate --noinput
python scripts/build_en_catalog.py
python manage.py collectstatic --noinput

touch tmp/restart.txt

echo "cPanel install/update finished."
echo "Next: edit .env for your domain, restart the app, then run: python manage.py createsuperuser"
