"""
Shared background event loop.

asyncpg bağlantı havuzu arka plan thread'inin loop'una bağlıdır.
Bolt handler thread'lerinden yapılan tüm async DB çağrıları bu loop üzerinden
run_coroutine_threadsafe ile yönlendirilmelidir — yoksa "attached to a different
loop" RuntimeError alınır.
"""

import asyncio
from typing import Coroutine, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def get_loop() -> asyncio.AbstractEventLoop:
    if _loop is None:
        raise RuntimeError("Background event loop not set yet. Is the service running?")
    return _loop


def run_async(coro: Coroutine[None, None, T], timeout: float = 30.0) -> T:
    """Bolt handler thread'inden async kodu çalıştırmak için kullanılır."""
    future = asyncio.run_coroutine_threadsafe(coro, get_loop())
    return future.result(timeout=timeout)
