"""
Event Service — Shared background event loop.

asyncpg baglanti havuzu arka plan thread'inin loop'una baglidir.
Bolt handler thread'lerinden yapilan tum async DB cagrilari bu loop uzerinden
run_coroutine_threadsafe ile yonlendirilmelidir — yoksa "attached to a different
loop" RuntimeError alinir.
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
    """Bolt handler thread'inden async kodu calistirmak icin kullanilir."""
    future = asyncio.run_coroutine_threadsafe(coro, get_loop())
    return future.result(timeout=timeout)
