"""
Evaluation Command Handlers
Bu komutlar sadece değerlendirme (evaluation) kanallarında çalışır.
"""
from __future__ import annotations

import json
import os

from slack_bolt import App
from sqlalchemy import select

from packages.database.manager import db
from packages.database.models.challenge import Challenge, ChallengeStatus
from packages.slack.client import slack_client
from ...core.event_loop import run_async
from ...logger import _logger
from ...manager import service_manager

app: App = slack_client.app


def _load_criteria() -> dict:
    """Değerlendirme kriterlerini criteria.json'dan yükler."""
    path = os.path.join(os.path.dirname(__file__), "../../config/criteria.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _logger.error("[CMD] Failed to load criteria.json: %s", e)
        return {"criteria": []}


def _is_evaluation_channel(channel_id: str) -> bool:
    """ChannelRegistry → evaluation kanalı mı?"""
    return service_manager.registry.has_evaluation(channel_id)


def handle_evaluate(client, body: dict) -> None:
    """
    Jüri değerlendirme modalini açar:
    - Kanalın evaluation kanalı olup olmadığını kontrol eder
    - Kullanıcının jüri üyesi olup olmadığını doğrular
    - criteria.json'dan soruları yükler ve modal açar
    """
    channel_id = body["channel_id"]
    user_id = body["user_id"]
    trigger_id = body["trigger_id"]

    # İzin kontrolü: sadece evaluation kanalında çalışır
    if not _is_evaluation_channel(channel_id):
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="⚠️ Bu komut yalnızca aktif bir değerlendirme kanalında kullanılabilir."
        )
        return

    async def _fetch():
        async with db.session(read_only=True) as session:
            from sqlalchemy.orm import joinedload, selectinload
            stmt = (
                select(Challenge)
                .where(
                    Challenge.evaluation_channel_id == channel_id,
                    Challenge.status.in_([ChallengeStatus.COMPLETED, ChallengeStatus.IN_EVALUATION]),
                )
                .options(
                    joinedload(Challenge.challenge_jury_members),
                    joinedload(Challenge.challenge_type),
                    selectinload(Challenge.challenge_team_members),
                )
            )
            result = await session.execute(stmt)
            return result.unique().scalars().first()

    challenge = run_async(_fetch())
    if not challenge:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="❌ Bu kanalda değerlendirmeye hazır (COMPLETED) bir challenge bulunamadı."
        )
        return

    # Jüri üyesi mi? Zaten değerlendirdi mi?
    jury_member = next(
        (jm for jm in challenge.challenge_jury_members if jm.slack_id == user_id),
        None,
    )
    if not jury_member:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="❌ Sadece atanan jüri üyeleri puanlama yapabilir."
        )
        return

    if (jury_member.meta or {}).get("evaluation"):
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="✅ Bu projeyi zaten değerlendirdiniz. Puanlamanız kaydedildi."
        )
        return

    # Proje bilgisi bloklarını oluştur
    submission = (challenge.meta or {}).get("submission", {})
    ct = challenge.challenge_type
    team_members = [
        tm.slack_id
        for tm in challenge.challenge_team_members
        if tm.slack_id
    ]
    team_mentions = " ".join(f"<@{uid}>" for uid in team_members) or "—"
    project_name = ct.name if ct else "Bilinmiyor"
    checklist = list(ct.checklist or []) if ct else []

    info_lines = [
        f"*📌 Proje:* {project_name}",
        f"*👥 Ekip:* {team_mentions}",
    ]
    if ct:
        info_lines.append(f"*⭐ Şablon puanı:* `{ct.points}`")
    if ct and ct.description:
        info_lines.append(f"*📝 Açıklama:* {ct.description}")
    github_url = submission.get("github_url", "")
    sub_description = submission.get("description", "")
    if github_url:
        info_lines.append(f"*🔗 GitHub:* <{github_url}>")
    if sub_description:
        info_lines.append(f"*💬 Teslim Notu:* {sub_description}")

    modal_blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(info_lines)},
        },
    ]
    if checklist:
        checklist_text = "*📋 Kabul Kriterleri:*\n" + "\n".join(f"• {item}" for item in checklist)
        modal_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": checklist_text},
        })
    modal_blocks.append({"type": "divider"})

    # criteria.json'dan değerlendirme sorularını oluştur
    config = _load_criteria()
    for item in config.get("criteria", []):
        if item["type"] == "boolean":
            modal_blocks.append({
                "type": "input",
                "block_id": f"crit_{item['id']}",
                "element": {
                    "type": "static_select",
                    "action_id": "val",
                    "placeholder": {"type": "plain_text", "text": "Seçiniz..."},
                    "options": [
                        {"text": {"type": "plain_text", "text": "✅ Evet (Uygun)"}, "value": "true"},
                        {"text": {"type": "plain_text", "text": "❌ Hayır (Yetersiz)"}, "value": "false"},
                    ],
                },
                "label": {"type": "plain_text", "text": item["name"]},
            })
        elif item["type"] == "scale":
            opts = [
                {"text": {"type": "plain_text", "text": str(i)}, "value": str(i)}
                for i in range(item["min"], item["max"] + 1)
            ]
            modal_blocks.append({
                "type": "input",
                "block_id": f"crit_{item['id']}",
                "element": {
                    "type": "static_select",
                    "action_id": "val",
                    "placeholder": {"type": "plain_text", "text": "Puan verin..."},
                    "options": opts,
                },
                "label": {"type": "plain_text", "text": item["name"]},
            })

    try:
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "jury_evaluation_view",
                "private_metadata": str(challenge.id),
                "title": {"type": "plain_text", "text": "Proje Değerlendirme"},
                "submit": {"type": "plain_text", "text": "Puanlamayı Gönder"},
                "blocks": modal_blocks,
            },
        )
    except Exception as e:
        _logger.error("[CMD] Failed to open evaluation modal: challenge=%s jury=%s error=%s", challenge.id, user_id, e)
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="⚠️ Değerlendirme formu açılamadı, lütfen tekrar deneyin."
        )
        return
    _logger.info("[CMD] Evaluation modal opened: challenge=%s jury=%s", challenge.id, user_id)
