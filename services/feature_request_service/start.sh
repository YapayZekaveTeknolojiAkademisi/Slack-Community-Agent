#!/usr/bin/env bash
# Feature Request Service — Process Manager
# Servis beklenmedik şekilde çökerse otomatik olarak yeniden başlatır.
#
# Kullanım:
#   ./start.sh              # Normal başlatma (RESUME modu)
#   ./start.sh --fresh      # Tabloları temizleyerek başlat (FRESH modu)
#   ./start.sh --daemon     # Arka planda başlat
#   ./start.sh --fresh --daemon

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
PID_FILE="$SCRIPT_DIR/.service.pid"
MAX_RESTARTS=10
RESTART_DELAY=5
DAEMON_MODE=false
FRESH_MODE=false
PYTHON_ARGS=""

# ---------------------------------------------------------------------------
# Argüman ayrıştırma
# ---------------------------------------------------------------------------
for arg in "$@"; do
    case $arg in
        --daemon) DAEMON_MODE=true ;;
        --fresh)  FRESH_MODE=true; PYTHON_ARGS="--fresh" ;;
        *) echo "Bilinmeyen argüman: $arg"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# Çalışıyor mu kontrolü
# ---------------------------------------------------------------------------
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Servis zaten çalışıyor (PID=$OLD_PID). Durdurmak için ./stop.sh kullanın."
        exit 1
    fi
    rm -f "$PID_FILE"
fi

# ---------------------------------------------------------------------------
# --fresh onayı (sadece interaktif modda)
# ---------------------------------------------------------------------------
if [ "$FRESH_MODE" = true ] && [ "$DAEMON_MODE" = false ] && [ -t 0 ]; then
    echo "⚠️  FRESH mod: feature_requests ve ilgili tüm tablolar temizlenecek!"
    read -r -p "Devam etmek için 'evet' yazın: " confirm
    if [ "$confirm" != "evet" ]; then
        echo "İptal edildi."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Daemon modu: kendini arka plana al
# ---------------------------------------------------------------------------
if [ "$DAEMON_MODE" = true ]; then
    nohup "$0" $PYTHON_ARGS >> "$LOG_DIR/feature_request_service.log" 2>&1 &
    DAEMON_PID=$!
    echo "$DAEMON_PID" > "$PID_FILE"
    echo "Servis arka planda başlatıldı (PID=$DAEMON_PID). Loglar: $LOG_DIR/feature_request_service.log"
    exit 0
fi

# ---------------------------------------------------------------------------
# Ana süreç PID'ini kaydet + temizle
# ---------------------------------------------------------------------------
echo "$$" > "$PID_FILE"
cleanup() {
    rm -f "$PID_FILE"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ---------------------------------------------------------------------------
# Yeniden başlatma döngüsü
# ---------------------------------------------------------------------------
restart_count=0
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/feature_request_service.log"; }

log "=== Servis başlatılıyor (mod=$([ "$FRESH_MODE" = true ] && echo FRESH || echo RESUME), MAX_RESTARTS=$MAX_RESTARTS) ==="

while [ "$restart_count" -lt "$MAX_RESTARTS" ]; do
    log "Başlatılıyor... (deneme $((restart_count + 1))/$MAX_RESTARTS)"

    set +e
    cd "$PROJECT_ROOT"
    # Sadece ilk başlatmada --fresh geçir; crash sonrası yeniden başlatmalarda RESUME kullan
    if [ "$restart_count" -eq 0 ]; then
        python -m services.feature_request_service $PYTHON_ARGS 2>&1 | tee -a "$LOG_DIR/feature_request_service.log"
    else
        python -m services.feature_request_service 2>&1 | tee -a "$LOG_DIR/feature_request_service.log"
    fi
    exit_code=${PIPESTATUS[0]}
    set -e

    # Normal / sinyal ile çıkış — yeniden başlatma
    if [ "$exit_code" -eq 0 ] || [ "$exit_code" -eq 130 ] || [ "$exit_code" -eq 143 ]; then
        log "Servis normal şekilde sonlandı (exit=$exit_code)."
        break
    fi

    restart_count=$((restart_count + 1))

    if [ "$restart_count" -lt "$MAX_RESTARTS" ]; then
        log "Servis beklenmedik şekilde durdu (exit=$exit_code). ${RESTART_DELAY}s sonra yeniden başlatılacak..."
        sleep "$RESTART_DELAY"
    else
        log "HATA: Maksimum yeniden başlatma sayısına ulaşıldı ($MAX_RESTARTS). Manuel müdahale gerekiyor."
    fi
done

rm -f "$PID_FILE"
