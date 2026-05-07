"""
Event Service — Entry Point

Başlatma sırası:
  1. Logger
  2. Background asyncio döngüsü + set_loop()
  3. DB + zamanlayıcı başlatma
  4. SIGINT/SIGTERM → `_shutdown()` bir kez planlanır + `stop` olayı
  5. (--socket ise) Slack `connect()` + ana thread `stop.wait()` — `start()` sonsuz beklemesi yok
  6. Kapanış: `_shutdown()` Future `result(timeout=120)` → Socket `close()` → loop durdur

Socket yaşam döngüsü `packages.slack.socket_runtime` ile challenge / summary ile aynıdır.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading
from typing import Any

from packages.database.manager import db
from packages.slack.client import slack_client
from packages.slack.socket_runtime import (
    close_socket_mode_safe,
    connect_socket_mode,
)

from services.event_service.logger import _logger  # noqa: F401 — start_logging
from services.event_service import handlers as _handlers  # noqa: F401
from packages.slack.community_help import setup_community_help_command

setup_community_help_command()
from services.event_service.core.event_loop import set_loop
from services.event_service.core.scheduler import event_scheduler


_SERVICE = "[Event Service]"


# ---------------------------------------------------------------------------
# Async başlatma & durdurma
# ---------------------------------------------------------------------------


async def _startup() -> None:
    """DB + scheduler'i başlatır."""
    db.initialize()
    _logger.info("%s Database connection pool initialized", _SERVICE)

    await event_scheduler.start()
    _logger.info("%s Scheduler started", _SERVICE)


async def _shutdown() -> None:
    """Scheduler'i durdurur, DB bağlantısını kapatır."""
    _logger.info("%s Stopping scheduler and releasing DB pool...", _SERVICE)
    await event_scheduler.stop()
    await db.shutdown()
    _logger.info("%s Service layer shutdown complete", _SERVICE)


# ---------------------------------------------------------------------------
# Background event loop
# ---------------------------------------------------------------------------


def _run_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    loop.run_forever()


def _schedule_shutdown(loop: asyncio.AbstractEventLoop, ref: dict[str, Any]) -> Any:
    """`_shutdown()` yalnızca bir Future olarak kuyruklandırılır."""
    fut = ref.get("future")
    if fut is not None:
        return fut
    ref["future"] = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
    return ref["future"]


def _install_signals(
    loop: asyncio.AbstractEventLoop,
    stop: threading.Event,
    shutdown_ref: dict[str, Any],
) -> None:
    def _on_signal(sig: int, _frame) -> None:
        _logger.info(
            "%s Signal %s received — initiating shutdown",
            _SERVICE,
            signal.Signals(sig).name,
        )
        _schedule_shutdown(loop, shutdown_ref)
        stop.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)


def _finalize(
    loop: asyncio.AbstractEventLoop,
    loop_thread: threading.Thread,
    shutdown_ref: dict[str, Any],
    *,
    close_socket: bool,
) -> None:
    fut = _schedule_shutdown(loop, shutdown_ref)
    try:
        fut.result(timeout=120)
    except Exception as exc:
        _logger.error("%s Shutdown wait error: %s", _SERVICE, exc)
    if close_socket:
        close_socket_mode_safe(slack_client.socket_handler, _logger, _SERVICE)
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=30)
    _logger.info("%s Exited cleanly", _SERVICE)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(use_socket: bool = False) -> None:
    loop = asyncio.new_event_loop()
    set_loop(loop)

    loop_thread = threading.Thread(target=_run_background_loop, args=(loop,), daemon=True, name="evt-bg-loop")
    loop_thread.start()
    _logger.info("%s Phase 1/5: Background asyncio loop started", _SERVICE)

    _logger.info("%s Phase 2/5: Database & scheduler startup...", _SERVICE)
    future_startup = asyncio.run_coroutine_threadsafe(_startup(), loop)
    try:
        future_startup.result(timeout=120)
    except Exception as exc:
        _logger.critical("%s Startup failed: %s", _SERVICE, exc, exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        sys.exit(1)

    shutdown_ref: dict[str, Any] = {"future": None}
    stop = threading.Event()
    _install_signals(loop, stop, shutdown_ref)
    _logger.info("%s Phase 3/5: Stop signals registered (SIGINT/SIGTERM)", _SERVICE)

    exit_code = 0
    try:
        if use_socket:
            _logger.info("%s Phase 4/5: Slack Socket Mode — connecting", _SERVICE)
            connect_socket_mode(slack_client.socket_handler, _logger, _SERVICE)
        else:
            _logger.info(
                "%s Phase 4/5: No Socket Mode in this process (scheduler + handler imports only)",
                _SERVICE,
            )
        _logger.info("%s Phase 5/5: Running — send SIGINT or SIGTERM to stop", _SERVICE)
        stop.wait()
    except Exception as exc:
        _logger.critical("%s Main loop error: %s", _SERVICE, exc, exc_info=True)
        exit_code = 1
    finally:
        _logger.info("%s Shutting down...", _SERVICE)
        _finalize(loop, loop_thread, shutdown_ref, close_socket=use_socket)

    sys.exit(exit_code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Event Service")
    parser.add_argument(
        "--socket",
        action="store_true",
        help="Slack Socket Mode bağla (tek başına çalışırken)",
    )
    args = parser.parse_args()
    main(use_socket=args.socket)
