"""Slack kullanıcı görünen adları — senkron `users_info`; `run_slack_io` ile çağrılmalı."""
from __future__ import annotations

from packages.slack.client import slack_client


def slack_display_names_for_users(user_ids: frozenset[str]) -> dict[str, str]:
    """Benzersiz Slack user ID'leri için ekranda gösterilecek ad (fallback: UID)."""
    out: dict[str, str] = {}
    bot = slack_client.bot_client
    for uid in user_ids:
        if uid in out or not uid:
            continue
        try:
            resp = bot.users_info(user=uid)
            if resp.get("ok"):
                u = resp.get("user") or {}
                profile = u.get("profile") or {}
                name = (
                    profile.get("display_name")
                    or profile.get("real_name")
                    or u.get("real_name")
                    or uid
                )
                out[uid] = name
            else:
                out[uid] = uid
        except Exception:
            out[uid] = uid
    return out
