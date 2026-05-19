"""
Slack Socket Mode — düzenli açma / kapanma.

Bolt `SocketModeHandler.start()` içinde `threading.Event().wait()` ile sonsuza kadar
bloklanır; SIGTERM/SIGINT bu beklemeden döndürmez. Bu modül `connect()` + paylaşılan
`stop` olayı ile ana thread’in sinyal sonrası `close()` çağırıp temiz çıkmasını sağlar.
"""
from __future__ import annotations

import signal
import threading
from typing import Any


def install_stop_signals(stop: threading.Event, logger, service_label: str) -> None:
    """SIGINT / SIGTERM yalnızca `stop` olayını tetikler (işleyici içinde ağır iş yapılmaz)."""

    def _on_signal(sig: int, _frame) -> None:  # noqa: ANN001
        logger.info(
            "%s Signal %s received — initiating shutdown",
            service_label,
            signal.Signals(sig).name,
        )
        stop.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)


def connect_socket_mode(socket_handler: Any, logger, service_label: str) -> None:
    """WebSocket oturumu açar (`start()` yerine)."""
    logger.info("%s Slack Socket Mode connecting...", service_label)
    socket_handler.connect()
    logger.info("%s Slack Socket Mode connected", service_label)


def close_socket_mode_safe(socket_handler: Any, logger, service_label: str) -> None:
    """WebSocket ve arka plan işçilerini güvenle kapatır (tekrar çağrıya dayanıklı)."""
    try:
        socket_handler.close()
    except Exception as exc:
        logger.warning("%s socket_handler.close() failed: %s", service_label, exc)
