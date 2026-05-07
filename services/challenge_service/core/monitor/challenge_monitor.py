import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Set

from packages.settings import get_settings
from ...logger import _logger
from ...utils.slack_helpers import slack_helper
from ..queue.channel_registry import ChannelRegistry, ChannelRecord

settings = get_settings()


class ChallengeMonitor:
    """
    Kanal Güvenlik Monitörü:
    - Registry'deki aktif kanalları periyodik olarak tarar, yetkisiz kullanıcıları uzaklaştırır.
    - Süresi dolmuş (TTL aşılmış) pending challenge'ları temizler.
    """

    def __init__(
        self,
        registry: ChannelRegistry,
        interval_seconds: int = 60,
        pending_challenges: "dict | None" = None,
        pending_lock: "threading.RLock | None" = None,
    ) -> None:
        self._registry = registry
        self._interval = interval_seconds
        self._pending_challenges = pending_challenges if pending_challenges is not None else {}
        self._pending_lock = pending_lock or threading.RLock()
        self._task: asyncio.Task | None = None
        self._running = False
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._bot_user_id = await asyncio.to_thread(slack_helper.get_bot_user_id)
        self._task = asyncio.create_task(self._run_loop())
        _logger.info("[MON] Challenge monitor up (%ss)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("[MON] Challenge monitor down")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.check_all_channels()
            except Exception as e:
                _logger.error("ChallengeMonitor error in loop: %s", e, exc_info=True)
            await asyncio.sleep(self._interval)

    async def check_all_channels(self) -> None:
        """Tüm registry kanallarını denetler ve stale pending'leri temizler."""
        challenges = self._registry.challenge_channels()
        evaluations = self._registry.evaluation_channels()

        for channel_id, record in {**challenges, **evaluations}.items():
            await self._check_channel(channel_id, record)

        await self._cleanup_stale_pending()

    async def _cleanup_stale_pending(self) -> None:
        """TTL'i geçmiş pending challenge'ları temizler, katılımcıları kuyruğa geri alır."""
        from ...core.queue.challenge_queue import QueueItem
        from ...manager import service_manager  # noqa: circular — safe (singleton zaten yaratılmış)

        ttl = get_settings().pending_challenge_ttl_minutes
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl)
        expired: list[tuple[str, dict]] = []

        with self._pending_lock:
            for pid, p in list(self._pending_challenges.items()):
                created_at = p.get("created_at")
                if created_at and created_at < cutoff:
                    expired.append((pid, dict(p)))
                    del self._pending_challenges[pid]

        for pid, p in expired:
            cat = p["category"]
            cat_label = cat.value.replace("_", " ").title()
            participants = p.get("participants", [])
            q = service_manager.category_queues[cat]
            requeued = []
            for uid in participants:
                if q.add(QueueItem(slack_id=uid)):
                    requeued.append(uid)
            _logger.warning(
                "[MON] Stale pending %s expired (%s, %d participants, requeued=%d)",
                pid,
                cat_label,
                len(participants),
                len(requeued),
            )
            if requeued:
                try:
                    mentions = " ".join(f"<@{uid}>" for uid in requeued)
                    text = (
                        f"{mentions}\n\n"
                        f"*{cat_label}* bekleme listeniz {ttl} dakika dolduğu için iptal edildi.\n"
                        "Kuyruğa geri alındınız — `/challenge join` ile tekrar katılabilirsiniz."
                    )
                    await asyncio.to_thread(
                        slack_helper.post_public_message,
                        settings.slack_challenge_channel,
                        text,
                    )
                except Exception as e:
                    _logger.warning("[MON] Could not notify expired pending participants: %s", e)

    async def _check_channel(self, channel_id: str, record: ChannelRecord) -> None:
        """Tek bir kanaldaki yetkisiz kullanıcıları temizler."""
        authorized_ids = self._get_authorized_ids(record)

        try:
            resp = await asyncio.to_thread(
                slack_helper.user_client.conversations_members,
                channel=channel_id,
            )
            if not resp.get("ok"):
                _logger.error("Failed to fetch members for %s: %s", channel_id, resp.get("error"))
                return

            actual_members = resp.get("members", [])
            intruders = [uid for uid in actual_members if uid not in authorized_ids]

            for intruder_id in intruders:
                _logger.warning("[SEC] Intruder kicked: %s in %s", intruder_id, channel_id)
                try:
                    await asyncio.to_thread(
                        slack_helper.user_client.conversations_kick,
                        channel=channel_id,
                        user=intruder_id,
                    )
                    await asyncio.to_thread(
                        slack_helper.send_announcement,
                        channel_id,
                        f"⚠️ <@{intruder_id}> yetkisiz erişim nedeniyle kanaldan uzaklaştırıldı.",
                    )
                except Exception as e:
                    _logger.error("Failed to kick %s from %s: %s", intruder_id, channel_id, e)

        except Exception as e:
            _logger.error("Error checking channel %s: %s", channel_id, e)

    def _get_authorized_ids(self, record: ChannelRecord) -> Set[str]:
        """Kayıtta olması gereken tüm yetkili ID'leri döner."""
        ids = set(record.members)
        ids.update(record.jury)
        if record.admin_slack_id:
            ids.add(record.admin_slack_id)
        if self._bot_user_id:
            ids.add(self._bot_user_id)

        if settings.slack_admin_slack_id:
            ids.add(settings.slack_admin_slack_id)
        if settings.slack_workspace_owner_id:
            ids.add(settings.slack_workspace_owner_id)

        return ids
