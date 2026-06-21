# SolarOps — Deployment Guide (Docker)

Production stack: **PostgreSQL + Redis + Gunicorn (ASGI/Uvicorn workers) + Celery + Nginx**, orchestrated with Docker Compose.

## 1. Prerequisites
- Docker Engine 24+ and Docker Compose v2+
- A server (Ubuntu 22.04+ recommended) with ports 80/443 open

## 2. Configuration
All configuration is via environment variables (12‑factor). Create a `.env` file **next to `docker-compose.yml`** for Compose interpolation:

```ini
SECRET_KEY=<generate-a-50-char-random-string>
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
POSTGRES_DB=solarops
POSTGRES_USER=solarops
POSTGRES_PASSWORD=<strong-password>
# Enable HTTPS redirect + HSTS once TLS is terminated (see §6)
SECURE_SSL_REDIRECT=1
```

The web/celery containers receive (from `docker-compose.yml`): `DEBUG=0`, `DATABASE_URL=postgres://…@db:5432/…`, `REDIS_URL=redis://redis:6379/0`, `USE_REDIS_CACHE=1`, `USE_REDIS_CHANNELS=1`.

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 3. Build & start
```bash
docker compose build
docker compose up -d
```
On first start the **web** container automatically waits for Postgres, runs `migrate`, and `collectstatic` (see `infrastructure/docker/entrypoint.sh`). Nginx serves the app on **http://server/**.

## 4. Create an admin user
```bash
docker compose exec web python manage.py createsuperuser
```

## 5. Services
| Service | Role |
|---|---|
| `db` | PostgreSQL 16 (volume `pgdata`) |
| `redis` | Redis 7 (cache, Celery broker, Channels layer) |
| `web` | Gunicorn + Uvicorn worker serving `solarops.asgi` (HTTP **and** WebSocket) |
| `celery` | Celery worker (aggregation/analytics/notification tasks) |
| `celery-beat` | Celery beat scheduler for periodic jobs |
| `nginx` | Reverse proxy; serves `/static/` & `/media/`, upgrades `/ws/` |

## 6. HTTPS (recommended)
Terminate TLS at Nginx (mount certs + add a `listen 443 ssl` server block in `infrastructure/docker/nginx.conf`) or front the stack with a TLS proxy (Caddy/Traefik/your load balancer). Then set `SECURE_SSL_REDIRECT=1`; the app already honours `X-Forwarded-Proto` and sends HSTS when `DEBUG=0`.

## 7. Operations
```bash
docker compose logs -f web            # tail app logs
docker compose exec web python manage.py migrate
docker compose exec db pg_dump -U solarops solarops > backup.sql   # DB backup
docker compose down                   # stop (data persists in volumes)
```

## 8. Scaling
- Stateless web tier: `docker compose up -d --scale web=4` (Nginx upstream load-balances).
- Run more Celery workers similarly: `--scale celery=3`.
- Postgres/Redis can be moved to managed services by changing `DATABASE_URL` / `REDIS_URL`.

## Notes
- **Bilingual (EN/FA)** and **dual calendar (Gregorian/Jalali)** work out of the box; the English message catalog (`locale/en/LC_MESSAGES/django.mo`) is built into the image. Rebuild it after changing translations with `python scripts/build_en_catalog.py`.
- The image installs prebuilt wheels (psycopg2-binary, Pillow, numpy/pandas/scikit-learn) — no compiler needed.
