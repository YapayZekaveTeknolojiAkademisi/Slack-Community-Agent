"""Embedding retry, clustering ve raporlama periyodik görevleri."""

import asyncio
import logging
from datetime import datetime, time, timedelta

_logger = logging.getLogger("feature_request_service.monitor")


class FeatureRequestMonitor:
    def __init__(self, service):
        self._svc = service
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self):
        self._running = True

        async def _check_vector_idle():
            from packages.vector import VectorClient

            VectorClient().unload_if_idle()

        self._tasks = [
            asyncio.create_task(
                self._daily(
                    time(3, 0), self._svc.retry_failed_embeddings, "embed_retry"
                )
            ),
            asyncio.create_task(
                self._weekly(
                    2, time(2, 0), self._svc.check_clustering_failed, "clust_fail_wed"
                )
            ),
            asyncio.create_task(
                self._weekly(
                    2, time(3, 0), self._svc.run_clustering_pipeline, "clust_wed"
                )
            ),
            asyncio.create_task(
                self._weekly(
                    5, time(9, 0), self._svc.check_clustering_failed, "clust_fail_sat"
                )
            ),
            asyncio.create_task(
                self._weekly(5, time(10, 0), self._svc.send_weekly_report, "report_sat")
            ),
            asyncio.create_task(
                self._periodic(900, _check_vector_idle, "vector_idle_check")
            ),
        ]
        _logger.info("[Monitor] %d görev başlatıldı", len(self._tasks))

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        _logger.info("[Monitor] Durduruldu")

    async def _periodic(self, interval_seconds: int, job, name: str):
        while self._running:
            try:
                await asyncio.sleep(interval_seconds)
                if self._running:
                    await job()
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error("[Monitor] %s: %s", name, e, exc_info=True)
                await asyncio.sleep(60)

    async def _daily(self, target: time, job, name: str):
        while self._running:
            now = datetime.now()
            nxt = datetime.combine(now.date(), target)
            if nxt <= now:
                nxt += timedelta(days=1)
            try:
                await asyncio.sleep((nxt - now).total_seconds())
                if self._running:
                    await job()
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error("[Monitor] %s: %s", name, e, exc_info=True)
                await asyncio.sleep(60)

    async def _weekly(self, dow: int, target: time, job, name: str):
        """dow: 0=Mon ... 6=Sun"""
        while self._running:
            now = datetime.now()
            days = (dow - now.weekday()) % 7
            if days == 0 and now.time() >= target:
                days = 7
            nxt = datetime.combine(now.date() + timedelta(days=days), target)
            try:
                await asyncio.sleep((nxt - now).total_seconds())
                if self._running:
                    await job()
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error("[Monitor] %s: %s", name, e, exc_info=True)
                await asyncio.sleep(60)
