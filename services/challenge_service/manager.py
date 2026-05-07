from __future__ import annotations

import asyncio
import threading
from enum import Enum
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.manager import db, DatabaseManager
from packages.database.models.challenge import (
    Challenge,
    ChallengeCategory,
    ChallengeJuryMember,
    ChallengeStatus,

    ChallengeTeamMember,
)
from packages.settings import get_settings, Settings
from .logger import _logger

from .core.queue.channel_registry import ChannelRegistry, _on_startup
from .core.queue.challenge_queue import CustomQueue
from .core.monitor.challenge_monitor import ChallengeMonitor
from .core.monitor.deadline_monitor import DeadlineMonitor
from .core.monitor.evaluation_monitor import EvaluationMonitor
from .core.engagement import engaged_from_registry_channel_views
from .utils.slack_helpers import slack_helper


# FRESH: tüm ilgili challenge satırlarını sil (challenges, team_members, jury_members; teslim meta challenge üzerinde) — tam sıfırlama
# RESUME: sadece NOT_STARTED temizlenir (takım oluşumu yarıda kaldı, bellek durumu kayıp)
#         STARTED / COMPLETED / IN_EVALUATION / EVALUATION_DELAYED → DB'de kalır, registry rebuild eder
#         EVALUATED / NOT_COMPLETED geçmişi RESUME modda korunur
_RESUME_CLEANUP_STATUSES = (ChallengeStatus.NOT_STARTED,)


class StartupMode(str, Enum):
    FRESH  = "fresh"
    """
    Tam sıfırlama: slack_users ve challenge_types dışındaki tüm challenge
    verilerini (challenges, team_members, jury_members, submissions) siler.
    Geliştirme/test ortamlarında veya servisi sıfırdan başlatmak için kullanılır.
    """
    RESUME = "resume"
    """
    Kısmi temizlik: sadece NOT_STARTED (takım oluşumu tamamlanmamış) challenge'ları
    temizler ve kanallarını arşivler. STARTED / COMPLETED / IN_EVALUATION /
    EVALUATION_DELAYED challenge'ları DB'de bırakır; registry _on_startup'ta yeniden
    doldurulur ve monitörler kaldığı yerden devam eder.
    EVALUATED ve NOT_COMPLETED geçmişi her zaman korunur.
    """


class ChallengeServiceManager:
    """
    Challenge Servisini orkestra eden ana sınıf (Singleton).
    Kuyrukları, Registry'yi ve Monitor sistemlerini başlatır/yönetir.
    """
    _instance: Optional[ChallengeServiceManager] = None
    _settings: Settings = get_settings()
    _db: DatabaseManager = db

    def __new__(cls) -> ChallengeServiceManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.registry = ChannelRegistry()

        self.jury_queue = CustomQueue(name="jury")
        self.category_queues: dict[ChallengeCategory, CustomQueue] = {
            cat: CustomQueue(name=f"challenge_{cat.value}") for cat in ChallengeCategory
        }

        self.pending_challenges: dict[str, dict] = {}
        self.pending_lock = threading.RLock()

        self.challenge_monitor = ChallengeMonitor(
            self.registry,
            interval_seconds=self._settings.monitor_challenge_interval,
            pending_challenges=self.pending_challenges,
            pending_lock=self.pending_lock,
        )
        self.deadline_monitor = DeadlineMonitor(
            self.registry,
            interval_seconds=self._settings.monitor_deadline_interval,
        )
        self.evaluation_monitor = EvaluationMonitor(
            self.registry,
            interval_seconds=self._settings.monitor_evaluation_interval,
        )

        self._initialized = True
        _logger.info("[SVC] Challenge manager init")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, mode: StartupMode = StartupMode.RESUME) -> None:
        """Servis bileşenlerini sırasıyla ayağa kaldırır."""
        _logger.info("[SVC] Starting challenge manager (mode=%s)", mode.value)

        # 1. DB temizliği
        await self._cleanup(mode)

        # 2. Bellek sıfırlama
        self._reset_memory()

        # 3. Registry'yi DB'den doldur
        async with self._db.session(read_only=True) as session:
            await _on_startup(
                registry=self.registry,
                session=session,
                admin_slack_id=self._settings.slack_admin_slack_id,
            )

        # 4. Monitörleri başlat
        await self.challenge_monitor.start()
        await self.deadline_monitor.start()
        await self.evaluation_monitor.start()

        _logger.info("[SVC] Challenge manager started (mode=%s)", mode.value)

    async def stop(self) -> None:
        """Servis bileşenlerini kapatır."""
        _logger.info("[SVC] Stopping challenge manager")
        await self.challenge_monitor.stop()
        await self.deadline_monitor.stop()
        await self.evaluation_monitor.stop()
        _logger.info("[SVC] Challenge manager stopped")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self, mode: StartupMode) -> None:
        """
        Mod'a göre DB'yi temizler.

        Adımlar:
          1. Silinecek challenge ID, kanal ve katılımcı verilerini çek.
          2. Katılımcılara bildirim gönder (silmeden önce).
          3. Slack kanallarını arşivle (hata olsa bile devam et).
          4. FK sırasına göre DB kayıtlarını sil.
        """
        # --- 1. Silinecek challenge verisi ---
        async with self._db.session(read_only=True) as session:
            challenge_ids, channel_ids = await self._fetch_targets(mode, session)
            cancel_data = await self._fetch_cancel_data(challenge_ids, session)

        if not challenge_ids:
            _logger.info("[SVC] Cleanup (%s): temizlenecek challenge yok", mode.value)
            return

        _logger.info(
            "[SVC] Cleanup (%s): %d challenge, %d kanal temizlenecek",
            mode.value, len(challenge_ids), len(channel_ids),
        )

        # --- 2. Katılımcılara bildirim (best-effort, silmeden önce) ---
        from .utils.notifications import notify_cancelled_challenges
        try:
            notify_cancelled_challenges(cancel_data)
        except Exception as e:
            _logger.warning("[SVC] Cancel notifications failed: %s", e)

        # --- 3. Slack kanallarını arşivle (best-effort) ---
        for channel_id in channel_ids:
            try:
                slack_helper.archive_channel(channel_id)
                _logger.info("[SVC] Archived channel %s", channel_id)
            except Exception as e:
                _logger.warning("[SVC] Could not archive channel %s: %s", channel_id, e)

        # --- 4. DB silme (FK sırasına göre) ---
        async with self._db.session() as session:
            await self._delete_challenge_data(challenge_ids, session)

        _logger.info("[SVC] Cleanup (%s) complete", mode.value)

    async def _fetch_targets(
        self,
        mode: StartupMode,
        session: AsyncSession,
    ) -> tuple[list[str], list[str]]:
        """Silinecek challenge ID'lerini ve aktif Slack kanal ID'lerini döner."""
        stmt = select(
            Challenge.id,
            Challenge.challenge_channel_id,
            Challenge.evaluation_channel_id,
        )
        if mode == StartupMode.RESUME:
            stmt = stmt.where(Challenge.status.in_(_RESUME_CLEANUP_STATUSES))

        result = await session.execute(stmt)
        rows = result.fetchall()

        challenge_ids = [row[0] for row in rows]
        channel_ids = list({
            cid
            for row in rows
            for cid in (row[1], row[2])
            if cid
        })
        return challenge_ids, channel_ids

    @staticmethod
    async def _fetch_cancel_data(
        challenge_ids: list[str],
        session: AsyncSession,
    ) -> list[tuple[str | None, list[str]]]:
        """Silinecek her challenge için (channel_id, [slack_id]) çiftini döner."""
        from sqlalchemy.orm import joinedload
        if not challenge_ids:
            return []
        result = await session.execute(
            select(Challenge)
            .where(Challenge.id.in_(challenge_ids))
            .options(joinedload(Challenge.challenge_team_members))
        )
        rows = []
        for ch in result.unique().scalars():
            slack_ids = [
                tm.slack_id
                for tm in ch.challenge_team_members
                if tm.slack_id
            ]
            rows.append((ch.challenge_channel_id, slack_ids))
        return rows

    @staticmethod
    async def _delete_challenge_data(
        challenge_ids: list[str],
        session: AsyncSession,
    ) -> None:
        """FK sırasına göre: submissions → jury → team → challenges."""
        await session.execute(
            delete(ChallengeJuryMember)
            .where(ChallengeJuryMember.challenge_id.in_(challenge_ids))
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            delete(ChallengeTeamMember)
            .where(ChallengeTeamMember.challenge_id.in_(challenge_ids))
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            delete(Challenge)
            .where(Challenge.id.in_(challenge_ids))
            .execution_options(synchronize_session=False)
        )
        _logger.info("[SVC] Deleted %d challenge records from DB", len(challenge_ids))

    # ------------------------------------------------------------------
    # Queue / pending helpers
    # ------------------------------------------------------------------

    def is_user_engaged(self, user_id: str) -> tuple[bool, str]:
        """
        Kullanıcı herhangi bir kuyrukta, pending challenge'da veya registry'de
        aktif challenge veya değerlendirme kaydında mı kontrol eder.

        Teslim sonrası takım challenge registry'de olmadığından, aynı kullanıcıların
        ``evaluation_channels`` içindeki ``members`` listesinde görünmesi gerekir
        (jüri atanana kadar dahil); böylece paralel yeni challenge'a girmeleri engellenir.

        Returns: (True/False, açıklama)
        """
        for cat, q in self.category_queues.items():
            if q.is_in_queue(user_id):
                return True, f"*{cat.value.upper()}* kuyruğundasınız"
        with self.pending_lock:
            for pid, p in self.pending_challenges.items():
                if user_id in p["participants"]:
                    cat_label = p["category"].value.replace("_", " ").title()
                    return True, f"*{cat_label}* challenge bekleme listesinde (`{pid}`)"
        engaged, reason = engaged_from_registry_channel_views(
            user_id,
            challenge_channels=self.registry.challenge_channels(),
            evaluation_channels=self.registry.evaluation_channels(),
        )
        if engaged:
            return True, reason
        return False, ""

    def re_enqueue(self, items: list, category: "ChallengeCategory") -> None:
        """Pop edilen QueueItem'ları kuyruğa geri ekler (başlatma başarısız olursa)."""
        q = self.category_queues[category]
        for item in items:
            q.add(item)
            _logger.info("[SVC] Re-enqueued %s to %s after failed launch", item.slack_id, category.value)

    # ------------------------------------------------------------------
    # Memory reset
    # ------------------------------------------------------------------

    def _reset_memory(self) -> None:
        """Tüm in-memory durumu sıfırlar."""
        self.registry.clear()
        with self.pending_lock:
            self.pending_challenges.clear()
        self.jury_queue.clear()
        for q in self.category_queues.values():
            q.clear()
        _logger.info("[SVC] In-memory state reset")


# Singleton instance
service_manager = ChallengeServiceManager()
