"""
Özet servisi — admin kanalı (`SLACK_ADMIN_CHANNEL`) günlükleri.

Challenge servisindeki gibi: emoji yok, kısa etiket + kısaltmalar, `[SUM]` öneki.
"""
from __future__ import annotations

from packages.settings import get_settings
from packages.slack.client import slack_client
from packages.slack.service_prefixes import PREFIX_SUMMARY

from ..logger import _logger


def _admin_sum(tag: str, detail: str) -> str:
    cleaned = " ".join((detail or "").split())
    return f"[{PREFIX_SUMMARY}] {tag}| {cleaned}"


def _safe_public(channel_id: str, text: str) -> None:
    if not (channel_id or "").strip():
        return
    try:
        slack_client.bot_client.chat_postMessage(channel=channel_id, text=text)
    except Exception as exc:
        _logger.warning("[Summary NOTIFY] admin post failed (channel=%s): %s", channel_id, exc)


def _trim_detail(s: str, max_len: int = 220) -> str:
    t = " ".join((s or "").split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def notify_summary_started_admin(
    *,
    scope: str,
    user_id: str,
    invoke_channel_id: str,
    hours: int,
    mode: str,
    target_channel_id: str | None = None,
) -> None:
    """Özet üretimi başladığında (kullanıcıya 'hazırlanıyor' ephemeral'ından sonra)."""
    admin = (get_settings().slack_admin_channel or "").strip()
    if not admin:
        return

    lines = [
        _admin_sum(
            "EVT",
            _trim_detail(
                f"summary_begin scope={scope} src_ch={invoke_channel_id} hrs={hours} mod={mode}"
            ),
        ),
        _admin_sum("KT", f"<@{user_id}>"),
    ]
    if scope == "single" and target_channel_id:
        lines.append(_admin_sum("INF", f"tgt_ch={target_channel_id}"))
    if scope == "all":
        lines.append(_admin_sum("INF", "rollup=all_member_channels"))

    _safe_public(admin, "\n".join(lines))


def notify_summary_finished_admin(
    *,
    scope: str,
    user_id: str,
    invoke_channel_id: str,
    hours: int,
    mode: str,
    status: str,
    detail: str = "",
) -> None:
    """
    Özet akışı sonlandığında (başarı, boş sonuç veya hata).

    status: ok | fail | empty
    detail: kısa istatistik veya rsn=... (Slack'te çok uzun olmasın)
    """
    admin = (get_settings().slack_admin_channel or "").strip()
    if not admin:
        return

    tail = _trim_detail(detail) if detail else ""
    evt_body = f"summary_end scope={scope} st={status} src_ch={invoke_channel_id} hrs={hours} mod={mode}"
    if tail:
        evt_body = f"{evt_body} {tail}"

    lines = [
        _admin_sum("EVT", evt_body),
        _admin_sum("KT", f"<@{user_id}>"),
    ]
    _safe_public(admin, "\n".join(lines))
