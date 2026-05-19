"""
Message Fetcher — Slack kanalından son 24 saatin mesajlarını çeker.

Özellikler:
- Pagination (cursor-based, 200/sayfa)
- Gürültü filtreleme (bot, join/leave vs.)
- Kullanıcı ID → isim çözümleme + cache
- Mention ve thread tespiti (kişiselleştirilmiş özet için)
- Çoklu kanal desteği (kullanıcının üye olduğu kanallar)
- reply_count olan üst mesajlar için `conversations_replies` ile thread gövdesi (sınırlı)
- `summary_min_words_per_message`: bu kelimeden kısa satırlar LLM özeline gönderilmez (0=kısıtlama yok)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from slack_sdk.errors import SlackApiError

from packages.settings import get_settings
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
    parent_thread_ts: str | None = None  # thread yanıtlarında üst mesajın ts'i (Slack thread_ts)


@dataclass
class ChannelInfo:
    """Kanal bilgisi."""
    id: str
    name: str
    is_private: bool = False
    member_count: int = 0


# Bot mesaj geçmişi okuyamıyor / kanal yok — "sessiz atlama" yerine raporlanır
_SLACK_FETCH_ACCESS_ERRORS = frozenset({
    "not_in_channel",
    "channel_not_found",
    "missing_scope",
    "is_archived",
})


@dataclass
class ChannelFetchOutcome:
    """Slack `conversations.history` + thread genişletme sonucu."""

    messages: list[ChannelMessage]
    slack_error: str | None = None


def slack_error_is_access_denied(error_code: str | None) -> bool:
    """Bot üyeliği / izin / kanal bulunamadı sınıfı hatalar."""
    return error_code in _SLACK_FETCH_ACCESS_ERRORS if error_code else False


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


def _word_count(text: str) -> int:
    """Basit kelime sayımı — boşlukla ayrılmış araç dizeleri."""
    return len(text.split())


def _parse_slack_channel_message(
    msg: dict,
    *,
    min_words: int = 0,
) -> ChannelMessage | None:
    """Slack conversations_history / replies tek satırından ChannelMessage."""
    if msg.get("subtype") in _SKIP_SUBTYPES:
        return None
    uid = msg.get("user")
    if not uid:
        return None
    text = (msg.get("text") or "").strip()
    if not text:
        return None
    if min_words > 0 and _word_count(text) < min_words:
        return None
    reactions = [r["name"] for r in msg.get("reactions", [])]
    mentions = _extract_mentions(text)
    raw_ts = msg["ts"]
    thread_ts = msg.get("thread_ts")
    is_reply = bool(thread_ts and thread_ts != raw_ts)
    parent_ts = thread_ts if is_reply else None
    return ChannelMessage(
        user_id=uid,
        user_name=_resolve_user_name(uid),
        text=text,
        ts=raw_ts,
        thread_reply_count=int(msg.get("reply_count") or 0),
        reactions=reactions,
        mentions=mentions,
        is_thread_reply=is_reply,
        parent_thread_ts=parent_ts,
    )


def _expand_roots_with_thread_replies(
    client,
    channel_id: str,
    messages: list[ChannelMessage],
    oldest_ts_str: str,
    *,
    max_threads: int,
    max_replies_per_thread: int,
    min_words: int = 0,
) -> list[ChannelMessage]:
    """
    Üst kanal sırasını koruyarak thread yanıtlarını ana mesajların hemen altına ekler.
    `max_threads==0` ise dokunulmaz.
    """
    if max_threads <= 0:
        return messages

    oldest_f = float(oldest_ts_str)
    expanded: list[ChannelMessage] = []
    threads_used = 0
    slack_limit_cap = min(200, max_replies_per_thread + 1)

    for msg in messages:
        expanded.append(msg)
        if msg.is_thread_reply or msg.thread_reply_count <= 0:
            continue
        if threads_used >= max_threads:
            continue

        try:
            resp = client.conversations_replies(
                channel=channel_id,
                ts=msg.ts,
                oldest=oldest_ts_str,
                limit=slack_limit_cap,
            )
        except Exception as exc:
            _logger.warning(
                "conversations_replies failed ch=%s parent_ts=%s: %s",
                channel_id,
                msg.ts,
                exc,
            )
            continue

        threads_used += 1
        raw_list = resp.get("messages") or []
        appended = 0
        for raw in raw_list:
            if raw.get("ts") == msg.ts:
                continue
            try:
                if float(raw["ts"]) < oldest_f:
                    continue
            except (TypeError, ValueError):
                continue
            child = _parse_slack_channel_message(raw, min_words=min_words)
            if child is None:
                continue
            if appended >= max_replies_per_thread:
                break
            expanded.append(child)
            appended += 1

    if threads_used:
        _logger.info(
            "Thread expansion: channel=%s parent_threads=%d → total lines=%d",
            channel_id,
            threads_used,
            len(expanded),
        )

    return expanded


def fetch_channel_messages_detailed(
    channel_id: str,
    hours: int = 24,
    max_messages: int = 500,
    *,
    max_threads: int | None = None,
    max_replies_per_thread: int | None = None,
) -> ChannelFetchOutcome:
    """
    Belirtilen kanaldan mesajları çeker; Slack hata kodunu `slack_error` olarak döndürebilir.

    `slack_error` dolu ve `messages` boş → geçmiş okunamadı (bot üyesi değil vb.).
    İkisi de boş değil pagination hatasında şu an kullanılmıyor; mesaj listesi yalnızca
    tam başarılı döngü sonunda dolu.
    """
    client = slack_client.bot_client
    oldest = str(
        (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    )

    settings = get_settings()
    mt = (
        settings.summary_max_threads_per_channel
        if max_threads is None
        else max_threads
    )
    mr = (
        settings.summary_max_replies_per_thread
        if max_replies_per_thread is None
        else max_replies_per_thread
    )
    mw = settings.summary_min_words_per_message

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
        except SlackApiError as exc:
            err = (
                (exc.response or {}).get("error")
                or "slack_api_error"
            )
            _logger.error(
                "conversations_history SlackApiError ch=%s code=%s",
                channel_id,
                err,
            )
            return ChannelFetchOutcome(messages=[], slack_error=err)
        except Exception as exc:
            _logger.error(
                "conversations_history failed for %s: %s",
                channel_id,
                exc,
                exc_info=True,
            )
            return ChannelFetchOutcome(messages=[], slack_error="request_failed")

        if not resp.get("ok", True):
            err = resp.get("error", "unknown_error")
            _logger.error("conversations_history ok=false ch=%s error=%s", channel_id, err)
            return ChannelFetchOutcome(messages=[], slack_error=err)

        for msg in resp.get("messages", []):
            row = _parse_slack_channel_message(msg, min_words=mw)
            if row is None:
                continue
            messages.append(row)

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    messages.reverse()

    expanded = _expand_roots_with_thread_replies(
        client,
        channel_id,
        messages,
        oldest,
        max_threads=mt,
        max_replies_per_thread=mr,
        min_words=mw,
    )

    _logger.info(
        "Fetched %d messages from channel %s (last %dh, with threads=%d lines)",
        len(expanded),
        channel_id,
        hours,
        len(expanded) - len(messages),
    )

    return ChannelFetchOutcome(messages=expanded, slack_error=None)


def fetch_channel_messages(
    channel_id: str,
    hours: int = 24,
    max_messages: int = 500,
    *,
    max_threads: int | None = None,
    max_replies_per_thread: int | None = None,
) -> list[ChannelMessage]:
    """
    Belirtilen kanalın son `hours` saatindeki mesajlarını çeker.

    Üst kanal satırlarından sonra , `reply_count > 0` olan kök mesajlar için
    zaman penceresine uyan thread yanıtları `conversations_replies` ile eklenir
    (`summary_max_*` ayarları veya parametrelerle sınırlı).

    Args:
        channel_id: Slack kanal ID'si (C...)
        hours: Geriye dönük kaç saat (varsayılan 24)
        max_messages: Maksimum kök mesaj sayısı (`conversations_history` üst limiti)
        max_threads: Bu çağrı için işlenecek maks thread kökü; None → ayar
        max_replies_per_thread: Thread başına en fazla yanıt satırı; None → ayar
        Kelime eşiği `summary_min_words_per_message` ile ayarlanır (0 = kapalı).

    Returns:
        ChannelMessage listesi (eskiden yeniye; thread yanları ara kökle bitişik).
        Hata ayırt etmek için `fetch_channel_messages_detailed` kullanın.
    """
    return fetch_channel_messages_detailed(
        channel_id,
        hours,
        max_messages,
        max_threads=max_threads,
        max_replies_per_thread=max_replies_per_thread,
    ).messages


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
    - Kullanıcının başlattığı üst mesaja gelen thread yanıtları (parent `ts` eşleşmesi)
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

        # Kullanıcının üst mesajına thread yanıtı mı? (Slack'te yanıtın ts'i parent'tan farklıdır)
        if (
            msg.is_thread_reply
            and msg.parent_thread_ts
            and msg.parent_thread_ts in user_message_timestamps
        ):
            is_relevant = True

        if is_relevant:
            personal.append(msg)

    return personal