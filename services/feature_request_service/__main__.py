"""
Feature Request Service — Entry Point
Başlatma: python -m services.feature_request_service
"""

import asyncio, signal, sys, threading

from packages.database.manager import db
from packages.slack.client import slack_client
from services.feature_request_service.logger import _logger
from services.feature_request_service import handlers as _handlers  # noqa: F401
from services.feature_request_service.core.event_loop import set_loop
from services.feature_request_service.manager import service_manager


async def _startup():
    db.initialize()
    _logger.info("[FR Service] DB initialized")
    await service_manager.start()
    _logger.info("[FR Service] Manager started")


async def _shutdown():
    _logger.info("[FR Service] Shutting down...")
    await service_manager.stop()
    await db.shutdown()
    _logger.info("[FR Service] Shutdown complete")


def _run_bg_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _install_signals(loop, stop_event):
    def _handle(sig, _):
        _logger.info("[FR Service] %s received", signal.Signals(sig).name)
        asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main():
    loop = asyncio.new_event_loop()
    set_loop(loop)
    t = threading.Thread(target=_run_bg_loop, args=(loop,), daemon=True, name="bg-loop")
    t.start()
    _logger.info("[FR Service] Event loop started")

    fut = asyncio.run_coroutine_threadsafe(_startup(), loop)
    try:
        fut.result(timeout=60)
    except Exception as e:
        _logger.critical("[FR Service] Startup failed: %s", e, exc_info=True)
        sys.exit(1)

    stop_event = threading.Event()
    _install_signals(loop, stop_event)

    _logger.info("[FR Service] Starting Socket Mode...")
    try:
        slack_client.socket_handler.start()
    except Exception as e:
        _logger.critical("[FR Service] Socket mode failed: %s", e, exc_info=True)
    finally:
        if not stop_event.is_set():
            f = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
            try:
                f.result(timeout=15)
            except:
                pass
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        _logger.info("[FR Service] Exited")


if __name__ == "__main__":
    main()
