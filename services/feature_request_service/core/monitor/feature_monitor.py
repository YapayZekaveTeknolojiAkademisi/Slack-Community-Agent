"""Embedding retry, clustering ve raporlama periyodik görevleri."""

import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from packages.settings import get_settings
from services.feature_request_service.logger import get_logger

_logger = get_logger("feature_request_service.monitor")


class FeatureRequestMonitor:
    def __init__(self, service):
        self._svc = service
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def _local_now(self) -> datetime:
        tz = ZoneInfo(get_settings().event_timezone)
        return datetime.now(tz)

    async def start(self):
        self._running = True

        async def _check_vector_idle():
            from packages.vector import VectorClient

            VectorClient().unload_if_idle()

        s = get_settings()
        self._tasks = [
            # Günlük: embedding_failed kayıtları yeniden dene
            asyncio.create_task(
                self._daily(
                    time(s.feature_request_embed_retry_hour, s.feature_request_embed_retry_minute),
                    self._svc.retry_failed_embeddings,
                    "embed_retry",
                )
            ),
            # Cumartesi öncesi kontrol: clustering_failed var mı?
            asyncio.create_task(
                self._weekly(
                    s.feature_request_report_weekday,
                    time(
                        s.feature_request_cluster_fail_before_report_hour,
                        s.feature_request_cluster_fail_before_report_minute,
                    ),
                    self._svc.check_clustering_failed,
                    "clust_fail_sat",
                )
            ),
            # Cumartesi: pipeline + rapor + temizlik (send_weekly_report içinde)
            asyncio.create_task(
                self._weekly(
                    s.feature_request_report_weekday,
                    time(s.feature_request_report_hour, s.feature_request_report_minute),
                    self._svc.send_weekly_report,
                    "report_sat",
                )
            ),
            # Periyodik: vektör modelini boşta ise bellekten boşalt
            asyncio.create_task(
                self._periodic(
                    s.feature_request_vector_idle_interval_seconds,
                    _check_vector_idle,
                    "vector_idle_check",
                )
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
            now = self._local_now()
            nxt = datetime.combine(now.date(), target, tzinfo=now.tzinfo)
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
        """dow: 0=Mon ... 6=Sun — saatler event_timezone ile yorumlanir."""
        while self._running:
            now = self._local_now()
            days = (dow - now.weekday()) % 7
            if days == 0 and now.time() >= target:
                days = 7
            nxt = datetime.combine(now.date() + timedelta(days=days), target, tzinfo=now.tzinfo)
            try:
                await asyncio.sleep((nxt - now).total_seconds())
                if self._running:
                    await job()
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error("[Monitor] %s: %s", name, e, exc_info=True)
                await asyncio.sleep(60)
