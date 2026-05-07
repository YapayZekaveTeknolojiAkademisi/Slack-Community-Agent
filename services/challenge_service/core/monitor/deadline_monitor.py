import asyncio
from datetime import datetime, timedelta, timezone

from packages.database.manager import db
from packages.database.models.challenge import ChallengeStatus
from packages.database.repository.challenge import ChallengeRepository
from ...logger import _logger
from ..queue.channel_registry import ChannelRegistry
from ...utils.slack_helpers import slack_helper


class DeadlineMonitor:
    """
    Süre Takibi Monitörü:
    Başlayan (STARTED) challenge'ların süresini kontrol eder.
    Süresi biten challenge'ları NOT_COMPLETED olarak işaretler.
    """

    def __init__(self, registry: ChannelRegistry, interval_seconds: int = 300) -> None:
        self._registry = registry
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        _logger.info("[MON] Deadline monitor up (%ss)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("[MON] Deadline monitor down")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.check_deadlines()
            except Exception as e:
                _logger.error("DeadlineMonitor error in loop: %s", e, exc_info=True)
            await asyncio.sleep(self._interval)

    async def check_deadlines(self) -> None:
        """Süresi dolan challenge'ları kontrol eder ve günceller."""
        async with db.session() as session:
            repo = ChallengeRepository(session)
            started_challenges = await repo.list_started()

            now = datetime.now(timezone.utc)
            for challenge in started_challenges:
                # 1. Başlangıç zamanı ve süre bilgisi kontrolü
                if not challenge.challenge_started_at or not challenge.challenge_type:
                    continue

                deadline_hours = challenge.challenge_type.deadline_hours or 48
                extended_hours = (challenge.meta or {}).get("extended_hours", 0)
                end_time = challenge.challenge_started_at + timedelta(hours=deadline_hours + extended_hours)

                if now > end_time:
                    _logger.info("[DL] Expired: %s", challenge.id)

                    ch_cid = challenge.challenge_channel_id
                    if ch_cid:
                        await asyncio.to_thread(
                            slack_helper.send_announcement,
                            ch_cid,
                            (
                                "⏱️ **Süre Doldu!**\n\n"
                                "Meydan okuma süresi tamamlandı ancak teslimat yapılmadı. "
                                "Kanal arşivleniyor."
                            ),
                        )
                        await asyncio.to_thread(slack_helper.archive_channel, ch_cid)
                        self._registry.unregister_challenge(ch_cid)

                    challenge.status = ChallengeStatus.NOT_COMPLETED
                    challenge.challenge_ended_at = now
                    challenge.challenge_channel_id = None
