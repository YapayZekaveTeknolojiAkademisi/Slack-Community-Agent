"""Event Service — Senkron Slack WebClient çağrılarını arka plan loop'ta thread'de çalıştırma.

Bolt handler iş parçacıkları asyncpg havuzunun bağlı olduğu event loop'u **bloklamamak** için
Slack SDK'nın senkron HTTP çağrılarını `asyncio.to_thread` üzerinden yönlendirir.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from ..core.event_loop import get_loop

T = TypeVar("T")


def run_slack_io(call: Callable[[], T], *, timeout: float = 60.0) -> T:
    """
    Bolt (veya senkron) bağlamından: Slack bloklayıcı çağrıları asyncio döngüsüne yükle,
    işi varsayılan executor'da çalıştır; döngü bloklanmadan görev sıralamaya devam eder.

    Scheduler tarafında tercih: ``await asyncio.to_thread(fn, *args)``
    (`core/scheduler.py`), bu yardımcı Bolt thread'inden kullanıma yöneliktir.
    """
    loop = get_loop()
    fut = asyncio.run_coroutine_threadsafe(asyncio.to_thread(call), loop)
    return fut.result(timeout=timeout)
