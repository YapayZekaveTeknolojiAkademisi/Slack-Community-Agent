# Event Service — build repository rootundan:
#   docker build -f services/event_service/Dockerfile -t slack-community-agent:event .
#
# Varsayilan: Slack Socket Mode acik (tek basina calisir). Sadece scheduler icin:
#   docker run ... slack-community-agent:event python -m services.event_service

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

RUN useradd --create-home --uid 1000 appuser && \
    mkdir -p /app/logs && \
    chown -R appuser:appuser /app
USER appuser

LABEL org.opencontainers.image.title="slack-community-agent-event"

CMD ["python", "-m", "services.event_service", "--socket"]
