"""
Challenge Service — Entry Point

Başlatma sırası:
  1. Logger
  2. DB bağlantısı
  3. Bolt handler'ları kayıt et
  4. Background event loop aç + set_loop()
  5. service_manager.start() (DB temizliği, registry, monitörler)
  6. Slack Socket Mode başlat (blocking)
  7. SIGINT/SIGTERM → graceful shutdown
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import threading

from packages.database.manager import db
from packages.slack.client import slack_client
from services.challenge_service import handlers as _handlers  # noqa: F401 — handler kayıtları aktive edilir
from services.feature_request_service import handlers as _fr_handlers  # noqa: F401 — feature_request handler'ları shared socket mode'a kaydedilir
from services.challenge_service.core.event_loop import set_loop
from services.challenge_service.logger import _logger
from services.challenge_service.manager import StartupMode, service_manager


# ---------------------------------------------------------------------------
# Async başlatma & durdurma
# ---------------------------------------------------------------------------

async def _startup(mode: StartupMode) -> None:
    """DB + service_manager'ı başlatır."""
    db.initialize()
    _logger.info("[Challenge Service] DB initialized")

    from packages.settings import get_settings as _gs
    if not _gs().smtp_enabled:
        _logger.warning("[Challenge Service] SMTP devre dışı — smtp_email/smtp_password tanımlı değil")

    await service_manager.start(mode=mode)
    _logger.info("[Challenge Service] Service manager started (mode=%s)", mode.value)

    # Registry dolduktan sonra aktif kanallara + ortak kanala bildirim gönder
    from services.challenge_service.utils.notifications import notify_startup
    try:
        notify_startup(registry=service_manager.registry)
    except Exception as exc:
        _logger.error("[Challenge Service] Startup notifications failed: %s", exc)


async def _shutdown() -> None:
    """Monitörleri durdurur, DB bağlantısını kapatır."""
    _logger.info("[Challenge Service] Shutting down...")

    # Registry + queue'lar temizlenmeden önce bildirim gönder
    from services.challenge_service.utils.notifications import notify_shutdown
    try:
        notify_shutdown(
            registry=service_manager.registry,
            category_queues=service_manager.category_queues,
            pending_lock=service_manager.pending_lock,
            pending_challenges=service_manager.pending_challenges,
        )
    except Exception as exc:
        _logger.error("[Challenge Service] Shutdown notifications failed: %s", exc)

    await service_manager.stop()
    await db.shutdown()
    _logger.info("[Challenge Service] Shutdown complete")


# ---------------------------------------------------------------------------
# Background event loop (Bolt handler thread'leri run_async ile buraya gelir)
# ---------------------------------------------------------------------------

def _run_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Ayrı bir thread'de çalışan async event loop."""
    loop.run_forever()


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: threading.Event) -> None:
    def _handle(sig: int, _frame) -> None:  # noqa: ANN001
        _logger.info("[Challenge Service] Signal %s received, initiating shutdown", signal.Signals(sig).name)
        asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(mode: StartupMode = StartupMode.RESUME) -> None:
    # 1. Background event loop'u oluştur ve ayrı thread'de başlat
    loop = asyncio.new_event_loop()
    set_loop(loop)

    loop_thread = threading.Thread(target=_run_background_loop, args=(loop,), daemon=True, name="bg-event-loop")
    loop_thread.start()
    _logger.info("[Challenge Service] Background event loop started")

    # 2. DB + servis başlatma (loop thread üzerinde)
    future = asyncio.run_coroutine_threadsafe(_startup(mode), loop)
    try:
        future.result(timeout=60)
    except Exception as exc:
        _logger.critical("[Challenge Service] Startup failed: %s", exc, exc_info=True)
        sys.exit(1)

    # 3. Graceful shutdown için stop event
    stop_event = threading.Event()
    _install_signal_handlers(loop, stop_event)

    # 4. Slack Socket Mode'u başlat (blocking — ana thread'i tutar)
    _logger.info("[Challenge Service] Starting Slack Socket Mode...")
    try:
        slack_client.socket_handler.start()
    except Exception as exc:
        _logger.critical("[Challenge Service] Socket mode failed: %s", exc, exc_info=True)
    finally:
        # Socket durdu ya da sinyal geldi
        if not stop_event.is_set():
            future = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
            try:
                future.result(timeout=15)
            except Exception as exc:
                _logger.error("[Challenge Service] Shutdown error: %s", exc)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        _logger.info("[Challenge Service] Exited cleanly")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Challenge Service")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Başlatmadan önce challenge/jury/submission tablolarını temizle (FRESH mod)",
    )
    args = parser.parse_args()
    main(mode=StartupMode.FRESH if args.fresh else StartupMode.RESUME)
