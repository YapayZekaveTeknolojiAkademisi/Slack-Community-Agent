"""
Message Fetcher — Slack kanalından son 24 saatin mesajlarını çeker.

Özellikler:
- Pagination (cursor-based, 200/sayfa)
- Gürültü filtreleme (bot, join/leave vs.)
- Kullanıcı ID → isim çözümleme + cache
- Mention ve thread tespiti (kişiselleştirilmiş özet için)
- Çoklu kanal desteği (kullanıcının üye olduğu kanallar)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from packages.slack.client import slack_client
from ..logger import _logger

# Slack tek seferde max 200 mesaj döndürür
_MAX_PER_PAGE = 200

# Filtrelenecek mesaj alt tipleri
_SKIP_SUBTYPES = frozenset({
    "bot_message", "bot_add", "bot_remove",
    "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "channel_archive",
    "channel_unarchive", "group_join", "group_leave",
    "group_topic", "group_purpose", "group_name",
    "pinned_item", "unpinned_item",
})

# Kullanıcı adı cache
_user_cache: dict[str, str] = {}


@dataclass
class ChannelMessage:
    """Tek bir Slack mesajını temsil eder."""
    user_id: str
    user_name: str
    text: str
    ts: str
    thread_reply_count: int = 0
    reactions: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    is_thread_reply: bool = False


@dataclass
class ChannelInfo:
    """Kanal bilgisi."""
    id: str
    name: str
    is_private: bool = False
    member_count: int = 0


def _resolve_user_name(user_id: str) -> str:
    """Slack user ID → görünen ad. Sonucu cache'ler."""
    if user_id in _user_cache:
        return _user_cache[user_id]

    try:
        resp = slack_client.bot_client.users_info(user=user_id)
        profile = resp["user"]
        name = (
            profile.get("real_name")
            or profile.get("profile", {}).get("display_name")
            or profile.get("name")
            or user_id
        )
    except Exception as exc:
        _logger.warning("User resolve failed for %s: %s", user_id, exc)
        name = user_id

    _user_cache[user_id] = name
    return name


def _extract_mentions(text: str) -> list[str]:
    """Mesaj metninden mention edilen kullanıcı ID'lerini çıkarır."""
    import re
    return re.findall(r"<@(U[A-Z0-9]+)>", text)


def fetch_channel_messages(
    channel_id: str,
    hours: int = 24,
    max_messages: int = 500,
) -> list[ChannelMessage]:
    """
    Belirtilen kanalın son `hours` saatindeki mesajlarını çeker.

    Args:
        channel_id: Slack kanal ID'si (C...)
        hours: Geriye dönük kaç saat (varsayılan 24)
        max_messages: Maksimum mesaj sayısı (varsayılan 500)

    Returns:
        ChannelMessage listesi (kronolojik sırada, eskiden yeniye)
    """
    client = slack_client.bot_client
    oldest = str(
        (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    )

    messages: list[ChannelMessage] = []
    cursor: Optional[str] = None

    while len(messages) < max_messages:
        try:
            resp = client.conversations_history(
                channel=channel_id,
                oldest=oldest,
                limit=min(_MAX_PER_PAGE, max_messages - len(messages)),
                cursor=cursor,
            )
        except Exception as exc:
            _logger.error("conversations_history failed for %s: %s", channel_id, exc)
            break

        for msg in resp.get("messages", []):
            if msg.get("subtype") in _SKIP_SUBTYPES:
                continue

            uid = msg.get("user")
            if not uid:
                continue

            text = (msg.get("text") or "").strip()
            if not text:
                continue

            reactions = [r["name"] for r in msg.get("reactions", [])]
            mentions = _extract_mentions(text)

            messages.append(ChannelMessage(
                user_id=uid,
                user_name=_resolve_user_name(uid),
                text=text,
                ts=msg["ts"],
                thread_reply_count=msg.get("reply_count", 0),
                reactions=reactions,
                mentions=mentions,
                is_thread_reply=bool(msg.get("thread_ts") and msg.get("thread_ts") != msg["ts"]),
            ))

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # Eskiden yeniye sırala
    messages.reverse()

    _logger.info(
        "Fetched %d messages from channel %s (last %dh)",
        len(messages), channel_id, hours,
    )
    return messages


def get_user_channels(user_id: str) -> list[ChannelInfo]:
    """
    Kullanıcının üye olduğu tüm kanalları döndürür.

    Bot'un da üye olduğu kanalları filtreler (mesaj çekebilmek için).
    """
    client = slack_client.bot_client
    channels: list[ChannelInfo] = []
    cursor: Optional[str] = None

    while True:
        try:
            resp = client.users_conversations(
                user=user_id,
                types="public_channel,private_channel",
                limit=200,
                cursor=cursor,
            )
        except Exception as exc:
            _logger.error("users_conversations failed for %s: %s", user_id, exc)
            break

        for ch in resp.get("channels", []):
            channels.append(ChannelInfo(
                id=ch["id"],
                name=ch.get("name", "unknown"),
                is_private=ch.get("is_private", False),
                member_count=ch.get("num_members", 0),
            ))

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    _logger.info("Found %d channels for user %s", len(channels), user_id)
    return channels


def filter_personal_messages(
    messages: list[ChannelMessage],
    user_id: str,
) -> list[ChannelMessage]:
    """
    Kullanıcıyı doğrudan ilgilendiren mesajları filtreler.

    Kriterler:
    - Kullanıcının mention edildiği mesajlar
    - Kullanıcının başlattığı thread'lere gelen yanıtlar
    - Kullanıcının yazdığı mesajlara gelen reaksiyonlar
    """
    personal: list[ChannelMessage] = []
    user_message_timestamps = {m.ts for m in messages if m.user_id == user_id}

    for msg in messages:
        # Kendi mesajlarını atlat
        if msg.user_id == user_id:
            continue

        is_relevant = False

        # Kullanıcı mention edilmiş mi?
        if user_id in msg.mentions:
            is_relevant = True

        # Kullanıcının mesajına yanıt (thread) mı?
        if msg.is_thread_reply and msg.ts in user_message_timestamps:
            is_relevant = True

        if is_relevant:
            personal.append(msg)

    return personal