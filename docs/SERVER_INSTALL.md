# SolarOps — Server Installation Guide (Ubuntu, without Docker)

For teams that prefer a bare‑metal / VM install instead of Docker. Target OS: **Ubuntu 22.04 LTS**.

## 1. System packages
```bash
sudo apt update && sudo apt install -y \
    python3.12 python3.12-venv python3-pip \
    postgresql postgresql-contrib \
    redis-server nginx git gettext
```
`gettext` is optional (used by Django's `compilemessages`); this project also ships a `polib`‑based catalog builder, so it is not required.

## 2. Database
```bash
sudo -u postgres psql <<'SQL'
CREATE DATABASE solarops;
CREATE USER solarops WITH PASSWORD 'strong-password';
GRANT ALL PRIVILEGES ON DATABASE solarops TO solarops;
ALTER DATABASE solarops OWNER TO solarops;
SQL
```

## 3. Application
```bash
sudo adduser --system --group solarops
sudo mkdir -p /opt/solarops && sudo chown solarops:solarops /opt/solarops
sudo -u solarops git clone <repo-url> /opt/solarops
cd /opt/solarops
sudo -u solarops python3.12 -m venv .venv
sudo -u solarops .venv/bin/pip install -r requirements.txt
```

Create `/opt/solarops/.env`:
```ini
DEBUG=0
SECRET_KEY=<random-50-chars>
ALLOWED_HOSTS=yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
DATABASE_URL=postgres://solarops:strong-password@127.0.0.1:5432/solarops
REDIS_URL=redis://127.0.0.1:6379/0
USE_REDIS_CACHE=1
USE_REDIS_CHANNELS=1
SECURE_SSL_REDIRECT=1
```

Migrate, collect static, create admin:
```bash
sudo -u solarops .venv/bin/python manage.py migrate
sudo -u solarops .venv/bin/python manage.py collectstatic --noinput
sudo -u solarops .venv/bin/python manage.py createsuperuser
```

## 4. Gunicorn (ASGI) service — `/etc/systemd/system/solarops.service`
```ini
[Unit]
Description=SolarOps (Gunicorn/Uvicorn)
After=network.target postgresql.service redis-server.service

[Service]
User=solarops
Group=solarops
WorkingDirectory=/opt/solarops
EnvironmentFile=/opt/solarops/.env
ExecStart=/opt/solarops/.venv/bin/gunicorn solarops.asgi:application \
    -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000 --workers 3
Restart=always

[Install]
WantedBy=multi-user.target
```

## 5. Celery services
`/etc/systemd/system/solarops-celery.service`:
```ini
[Unit]
Description=SolarOps Celery worker
After=network.target redis-server.service
[Service]
User=solarops
WorkingDirectory=/opt/solarops
EnvironmentFile=/opt/solarops/.env
ExecStart=/opt/solarops/.venv/bin/celery -A solarops worker -l info
Restart=always
[Install]
WantedBy=multi-user.target
```
(Repeat with `celery -A solarops beat -l info` for `solarops-celery-beat.service`.)

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now solarops solarops-celery solarops-celery-beat
```

## 6. Nginx — `/etc/nginx/sites-available/solarops`
```nginx
server {
    listen 80;
    server_name yourdomain.com;
    client_max_body_size 20M;

    location /static/ { alias /opt/solarops/staticfiles/; expires 30d; }
    location /media/  { alias /opt/solarops/media/; expires 30d; }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/solarops /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 7. HTTPS
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

## 8. Health checks
- App: `curl -I http://127.0.0.1:8000/accounts/login/` → `200`
- Logs: `journalctl -u solarops -f` and `/opt/solarops/logs/app.log`
