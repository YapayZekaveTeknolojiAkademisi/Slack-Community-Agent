"""
Challenge Service — Entry Point

Başlatma sırası:
  1. Logger
  2. Bolt handler içe aktarımları (challenge, özet, özellik isteği, event, english, summary)
  3. Background `asyncio` döngüsü (+ run_async için set_loop)
  4. Veritabanı + challenge_types seed + service_manager.start()
  5. SIGINT/SIGTERM → `stop` olayı
  6. Slack Socket Mode `connect()` + ana thread `stop.wait()` (`start()` sonsuz beklemez)
  7. Kapanış: `_shutdown()` → Socket `close()` → loop durdur → thread join

Socket yaşam döngüsü summary servisi ile aynı `packages.slack.socket_runtime` kullanır.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading

from packages.database.manager import db
from packages.slack.client import slack_client
from packages.slack.socket_runtime import (
    close_socket_mode_safe,
    connect_socket_mode,
    install_stop_signals,
)

from services.challenge_service.logger import _logger  # noqa: F401 — start_logging

# /channel-summary — challenge ile tek Socket; doğrudan yükle (Bolt kaydı garanti).
import services.summary_service.handlers.commands.summary  # noqa: F401

from services.challenge_service import handlers as _handlers  # noqa: F401
from services.feature_request_service import handlers as _fr_handlers  # noqa: F401
from services.event_service import handlers as _evt_handlers  # noqa: F401
from services.challenge_service.core.event_loop import set_loop
from services.event_service.core.event_loop import set_loop as set_event_service_loop
from services.feature_request_service.core.event_loop import set_loop as set_feature_request_loop
from services.english_service.handlers import setup_english_handlers
from packages.slack.community_help import setup_community_help_command
from services.challenge_service.manager import StartupMode, service_manager

setup_english_handlers()
setup_community_help_command()

_SERVICE = "[Challenge Service]"


# ---------------------------------------------------------------------------
# Async başlatma & durdurma
# ---------------------------------------------------------------------------


async def _startup(mode: StartupMode) -> None:
    """DB + service_manager'ı başlatır."""
    db.initialize()
    _logger.info("%s Database connection pool initialized", _SERVICE)

    from packages.challenge_type_seeds import sync_challenge_types

    try:
        async with db.session() as session:
            await sync_challenge_types(session)
    except ValueError as exc:
        _logger.critical("%s challenge_types seed başarısız: %s", _SERVICE, exc)
        raise
    except Exception as exc:
        _logger.critical("%s challenge_types seed I/O veya DB hatası: %s", _SERVICE, exc, exc_info=True)
        raise

    from packages.settings import get_settings as _gs

    if not _gs().smtp_enabled:
        _logger.warning("%s SMTP devre dışı — smtp_email/smtp_password tanımlı değil", _SERVICE)

    await service_manager.start(mode=mode)
    _logger.info("%s Service manager started (mode=%s)", _SERVICE, mode.value)

    from services.challenge_service.utils.notifications import notify_startup

    try:
        notify_startup(registry=service_manager.registry)
    except Exception as exc:
        _logger.error("%s Startup notifications failed: %s", _SERVICE, exc)


async def _shutdown() -> None:
    """Monitörleri durdurur, DB bağlantısını kapatır."""
    _logger.info("%s Stopping monitors and releasing DB pool...", _SERVICE)

    from services.challenge_service.utils.notifications import notify_shutdown

    try:
        notify_shutdown(
            registry=service_manager.registry,
            category_queues=service_manager.category_queues,
            pending_lock=service_manager.pending_lock,
            pending_challenges=service_manager.pending_challenges,
        )
    except Exception as exc:
        _logger.error("%s Shutdown notifications failed: %s", _SERVICE, exc)

    await service_manager.stop()
    await db.shutdown()
    _logger.info("%s Service layer shutdown complete", _SERVICE)


# ---------------------------------------------------------------------------
# Background event loop
# ---------------------------------------------------------------------------


def _run_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    loop.run_forever()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(mode: StartupMode = StartupMode.RESUME) -> None:
    _logger.info("%s Phase 1/6: Logger initialized — loading handlers...", _SERVICE)
    loop = asyncio.new_event_loop()
    set_loop(loop)
    set_event_service_loop(loop)
    set_feature_request_loop(loop)

    loop_thread = threading.Thread(target=_run_background_loop, args=(loop,), daemon=True, name="bg-event-loop")
    loop_thread.start()
    _logger.info("%s Phase 2/6: Background asyncio loop started", _SERVICE)

    _logger.info("%s Phase 3/6: Database & service_manager startup...", _SERVICE)
    future_startup = asyncio.run_coroutine_threadsafe(_startup(mode), loop)
    try:
        future_startup.result(timeout=120)
    except Exception as exc:
        _logger.critical("%s Startup failed: %s", _SERVICE, exc, exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        sys.exit(1)

    stop = threading.Event()
    install_stop_signals(stop, _logger, _SERVICE)
    _logger.info("%s Phase 4/6: Stop signals registered (SIGINT/SIGTERM)", _SERVICE)

    exit_code = 0
    try:
        _logger.info("%s Phase 5/6: Slack Socket Mode — connecting", _SERVICE)
        connect_socket_mode(slack_client.socket_handler, _logger, _SERVICE)
        _logger.info("%s Phase 6/6: Running — send SIGINT or SIGTERM to stop", _SERVICE)
        stop.wait()
    except Exception as exc:
        _logger.critical("%s Socket Mode error: %s", _SERVICE, exc, exc_info=True)
        exit_code = 1
    finally:
        _logger.info("%s Shutting down...", _SERVICE)
        future_sd = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        try:
            future_sd.result(timeout=120)
        except Exception as exc:
            _logger.error("%s Async shutdown error: %s", _SERVICE, exc)
        close_socket_mode_safe(slack_client.socket_handler, _logger, _SERVICE)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=30)
        _logger.info("%s Exited cleanly", _SERVICE)

    sys.exit(exit_code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Challenge Service")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Başlatmadan önce tüm challenge kayıtlarını temizle (takım/jüri ilişkileri; FRESH mod)",
    )
    args = parser.parse_args()
    main(mode=StartupMode.FRESH if args.fresh else StartupMode.RESUME)
