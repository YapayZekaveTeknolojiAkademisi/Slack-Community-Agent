# Event Service — build repository rootundan:
#   docker build -f services/event_service/Dockerfile -t slack-community-agent:event .
#
# Varsayılan CMD: Socket yok — compose ile uyumlu (challenge Socket tutar).
# Tek başına Socket için: CMD override veya `--socket` ile çalıştırın.

FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY packages ./packages
COPY services ./services
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY docker/entrypoint-appuser-hfcache.sh /usr/local/bin/entrypoint.sh

RUN useradd --create-home --uid 1000 appuser && \
    mkdir -p /app/logs && \
    chown -R appuser:appuser /app && \
    chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Varsayılan: Socket yok (docker-compose'taki gibi; challenge Socket tutar).
# Tek başına koşarken: python -m services.event_service --socket
CMD ["python", "-m", "services.event_service"]

LABEL org.opencontainers.image.title="slack-community-agent-event"
