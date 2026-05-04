"""
Event Service — Entry Point

Baslama sirasi:
  1. Logger
  2. DB baglantisi
  3. Bolt handler'lari kayit et
  4. Background event loop ac + set_loop()
  5. Scheduler baslat
  6. (Opsiyonel) Slack Socket Mode baslat (--socket flag'i ile)
  7. SIGINT/SIGTERM → graceful shutdown

Kullanim:
  # Bagimsiz calistirma (kendi Socket Mode'u ile)
  python -m services.event_service --socket

  # Sadece handler kayit + scheduler (Socket Mode baska process'te)
  python -m services.event_service
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading

from services.event_service.logger import _logger  # noqa: F401 — start_logging (önce)
from packages.database.manager import db
from packages.slack.client import slack_client
from services.event_service import handlers as _handlers  # noqa: F401 — handler kayitlari aktive edilir
from services.event_service.core.event_loop import set_loop
from services.event_service.core.scheduler import event_scheduler


# ---------------------------------------------------------------------------
# Async baslama & durdurma
# ---------------------------------------------------------------------------

async def _startup() -> None:
    """DB + scheduler'i baslatir."""
    db.initialize()
    _logger.info("[Event Service] DB initialized")

    await event_scheduler.start()
    _logger.info("[Event Service] Scheduler started")


async def _shutdown() -> None:
    """Scheduler'i durdurur, DB baglantisini kapatir."""
    _logger.info("[Event Service] Shutting down...")
    await event_scheduler.stop()
    await db.shutdown()
    _logger.info("[Event Service] Shutdown complete")


# ---------------------------------------------------------------------------
# Background event loop (Bolt handler thread'leri run_async ile buraya gelir)
# ---------------------------------------------------------------------------

def _run_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Ayri bir thread'de calisan async event loop."""
    loop.run_forever()


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: threading.Event) -> None:
    def _handle(sig: int, _frame) -> None:
        _logger.info("[Event Service] Signal %s received, initiating shutdown", signal.Signals(sig).name)
        asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(use_socket: bool = False) -> None:
    # 1. Background event loop'u olustur ve ayri thread'de baslat
    loop = asyncio.new_event_loop()
    set_loop(loop)

    loop_thread = threading.Thread(target=_run_background_loop, args=(loop,), daemon=True, name="evt-bg-loop")
    loop_thread.start()
    _logger.info("[Event Service] Background event loop started")

    # 2. DB + scheduler baslatma (loop thread uzerinde)
    future = asyncio.run_coroutine_threadsafe(_startup(), loop)
    try:
        future.result(timeout=60)
    except Exception as exc:
        _logger.critical("[Event Service] Startup failed: %s", exc, exc_info=True)
        sys.exit(1)

    # 3. Graceful shutdown icin stop event
    stop_event = threading.Event()
    _install_signal_handlers(loop, stop_event)

    if use_socket:
        # 4a. Slack Socket Mode'u baslat (blocking — ana thread'i tutar)
        _logger.info("[Event Service] Starting Slack Socket Mode...")
        try:
            slack_client.socket_handler.start()
        except Exception as exc:
            _logger.critical("[Event Service] Socket mode failed: %s", exc, exc_info=True)
        finally:
            if not stop_event.is_set():
                future = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
                try:
                    future.result(timeout=15)
                except Exception as exc:
                    _logger.error("[Event Service] Shutdown error: %s", exc)
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
            _logger.info("[Event Service] Exited cleanly")
    else:
        # 4b. Socket Mode yok — handler'lar kayitli, scheduler calisiyor, sinyal bekle
        _logger.info("[Event Service] Running without Socket Mode (handlers registered, scheduler active)")
        _logger.info("[Event Service] Waiting for signal to stop...")
        try:
            stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            if not stop_event.is_set():
                future = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
                try:
                    future.result(timeout=15)
                except Exception as exc:
                    _logger.error("[Event Service] Shutdown error: %s", exc)
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
            _logger.info("[Event Service] Exited cleanly")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Event Service")
    parser.add_argument(
        "--socket",
        action="store_true",
        help="Slack Socket Mode'u baslat (bagimsiz calistirma icin)",
    )
    args = parser.parse_args()
    main(use_socket=args.socket)
