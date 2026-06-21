FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUTF8=1

WORKDIR /app

# libpq5 for psycopg2 runtime; curl for healthchecks. (Pillow/psycopg2-binary ship wheels.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x infrastructure/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["infrastructure/docker/entrypoint.sh"]
# Serve the ASGI app (HTTP + WebSocket) via Gunicorn + Uvicorn workers.
CMD ["gunicorn", "solarops.asgi:application", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
