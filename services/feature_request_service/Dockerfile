# Feature Request Service — build repository rootundan:
#   docker build -f services/feature_request_service/Dockerfile -t slack-community-agent:feature-request .

FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# umap-learn → Numba JIT önbelleği yazılabilir dizinde tutulur (site-packages’a yazılamaz).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    NUMBA_CACHE_DIR=/tmp/numba-cache

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
CMD ["python", "-m", "services.feature_request_service"]

LABEL org.opencontainers.image.title="slack-community-agent-feature-request"
