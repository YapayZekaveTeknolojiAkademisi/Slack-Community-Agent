import asyncio
from datetime import datetime, timezone

from packages.database.manager import db
from packages.database.models.challenge import ChallengeStatus
from packages.database.repository.challenge import ChallengeRepository
from packages.settings import get_settings
from ...logger import _logger
from ..queue.channel_registry import ChannelRegistry
from ...utils.slack_helpers import slack_helper

class EvaluationMonitor:
    """
    Değerlendirme Takibi Monitörü:
    Jüri değerlendirme süresini izler.
    Geciken jirilere hatırlatma gönderir.
    Süre aşımı devam ederse durumu EVALUATION_DELAYED olarak işaretler.
    """

    def __init__(self, registry: ChannelRegistry, interval_seconds: int = 600) -> None:
        self._registry = registry
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        _logger.info("[MON] Evaluation monitor up (%ss)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("[MON] Evaluation monitor down")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.check_evaluations()
            except Exception as e:
                _logger.error("EvaluationMonitor error in loop: %s", e, exc_info=True)
            await asyncio.sleep(self._interval)

    async def check_evaluations(self) -> None:
        """Değerlendirmesi geciken jürileri ve challenge'ları kontrol eder."""
        settings = get_settings()
        # Hatırlatma eşiği (örn: 24 saat)
        reminder_threshold_hours = settings.evaluation_max_wait_hours
        # Kesin başarısızlık eşiği (örn: 24h + 24h = 48 saat)
        fail_threshold_hours = reminder_threshold_hours * 2

        async with db.session() as session:
            repo = ChallengeRepository(session)
            in_evaluation = await repo.list_in_evaluation()
            
            now = datetime.now(timezone.utc)
            for challenge in in_evaluation:
                if not challenge.evaluation_started_at:
                    continue
                
                # Değerlendirme başlamış, ne kadar süre geçti?
                elapsed = now - challenge.evaluation_started_at
                elapsed_hours = elapsed.total_seconds() / 3600

                # 1. Senaryo: hatırlatma eşiğinin 2 katı aşıldıysa (kesin zaman aşımı)
                if elapsed_hours >= fail_threshold_hours:
                    _logger.warning(
                        "[EVAL] Timeout (%sh): %s",
                        int(fail_threshold_hours),
                        challenge.id,
                    )

                    if challenge.evaluation_channel_id:
                        ecid = challenge.evaluation_channel_id
                        slack_helper.send_announcement(
                            channel_id=ecid,
                            text=(
                                f"🚨 **Değerlendirme Zaman Aşımı!**\n\n"
                                f"Jüri değerlendirmesi {int(fail_threshold_hours)} saat içinde tamamlanamadı. "
                                "Süreç başarısız olarak sonlandırılıyor."
                            ),
                        )
                        slack_helper.archive_channel(ecid)
                        self._registry.unregister_evaluation(ecid)
                        # Arşivlendi; yoksa RESUME sonrası _on_startup EVALUATION_DELAYED için bu ID ile registry doldurur
                        challenge.evaluation_channel_id = None

                    challenge.status = ChallengeStatus.EVALUATION_DELAYED
                    challenge.evaluation_ended_at = now
                    continue

                # 2. Senaryo: hatırlatma eşiği aşıldı (EVALUATION_MAX_WAIT_HOURS)
                if elapsed_hours >= reminder_threshold_hours:
                    meta = challenge.meta or {}
                    if not meta.get("evaluation_reminder_sent"):
                        _logger.info("[EVAL] Reminder sent: %s", challenge.id)
                        
                        if challenge.evaluation_channel_id:
                            # Jüri üyelerini etiketleyebiliriz
                            jury_mentions = " ".join([f"<@{jm.slack_id}>" for jm in challenge.challenge_jury_members if jm.slack_id])
                            
                            slack_helper.send_announcement(
                                channel_id=challenge.evaluation_channel_id,
                                text=(
                                    f"🔔 **Hatırlatma!**\n\n{jury_mentions} "
                                    f"Değerlendirme süreci {int(reminder_threshold_hours)} saattir devam ediyor. "
                                    "Lütfen sonuçları en kısa sürede iletin. "
                                    f"Kalan süre: **{max(0, int(fail_threshold_hours - elapsed_hours))} saat**."
                                ),
                            )
                        
                        meta["evaluation_reminder_sent"] = True
                        challenge.meta = meta
            
            await session.commit()
