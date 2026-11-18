#!/bin/sh
set -eu

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$APP_DIR"

PYTHON_BIN="${PYTHON:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "Python was not found. Activate the cPanel Python App virtualenv first, then rerun this script." >&2
    echo "Example: source ~/virtualenv/parsenergy/3.11/bin/activate" >&2
    exit 1
  fi
fi

if [ ! -f manage.py ]; then
  echo "manage.py not found. Run this script from the SolarOps app root." >&2
  exit 1
fi

mkdir -p logs tmp media staticfiles

if [ ! -f .env ]; then
  cp .env.cpanel.example .env
  "$PYTHON_BIN" - <<'PY'
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

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements-cpanel.txt

"$PYTHON_BIN" manage.py migrate --noinput
"$PYTHON_BIN" scripts/build_en_catalog.py
"$PYTHON_BIN" manage.py collectstatic --noinput

touch tmp/restart.txt

echo "cPanel install/update finished."
echo "Next: edit .env for your domain, restart the app, then run: python manage.py createsuperuser"
