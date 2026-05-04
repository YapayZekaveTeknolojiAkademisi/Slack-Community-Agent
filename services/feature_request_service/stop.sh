#!/usr/bin/env bash
# Feature Request Service — Durdurma Scripti

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.service.pid"
WAIT_SECONDS=10

if [ ! -f "$PID_FILE" ]; then
    echo "Servis çalışmıyor (PID dosyası bulunamadı)."
    exit 0
fi

PID=$(cat "$PID_FILE")

if ! kill -0 "$PID" 2>/dev/null; then
    echo "Servis zaten durmuş (PID=$PID)."
    rm -f "$PID_FILE"
    exit 0
fi

echo "Servis durduruluyor (PID=$PID)..."
kill -TERM "$PID"

for _ in $(seq 1 "$WAIT_SECONDS"); do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "Servis durduruldu."
        rm -f "$PID_FILE"
        exit 0
    fi
    sleep 1
done

echo "Servis ${WAIT_SECONDS}s içinde durmadı, zorla kapatılıyor..."
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Servis zorla kapatıldı."

# Güvenlik: her durumda PID dosyası kalmadığından emin ol
rm -f "$PID_FILE"
