from __future__ import annotations

from datetime import datetime

from slack_bolt import Ack, App

from packages.slack.client import slack_client
from packages.slack.blocks.builder import MessageBuilder
from ...logger import _logger
from ...core.constants import MONTH_NAMES_TR, DEPT_DISPLAY_NAMES
from ...core.training_fetcher import detect_department, fetch_monthly_trainings, filter_trainings

app: App = slack_client.app

@app.command("/this-month")
def handle_this_month(ack: Ack, body: dict, client):
    ack()

    user_id = body.get("user_id")
    channel_id = body.get("channel_id")

    try:
        user_info = client.users_info(user=user_id)
        profile = user_info.get("user", {}).get("profile", {})
        title = profile.get("title", "")
    except Exception as exc:
        _logger.error("[this-month] Slack users_info failed for %s: %s", user_id, exc)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⚠️ Profil bilgilerine ulaşılamadı. Lütfen tekrar deneyin.",
        )
        return

    department = detect_department(title)
    if not department:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=(
                "⚠️ Slack profilinde bölüm bilgisi bulunamadı.\n\n"
                "Profilinizdeki *Başlık (Title)* alanını aşağıdakilerden biriyle güncelleyin:\n"
                "• `Yapay Zeka`\n"
                "• `Veri Bilimi`\n"
                "• `No Code/Low Code`\n\n"
                f"_Mevcut başlığınız: `{title or '(boş)'}`_"
            ),
        )
        return

    now = datetime.now()
    month_name = MONTH_NAMES_TR.get(now.month)
    if not month_name:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⚠️ Bu ay için takvim bilgisi bulunamadı.",
        )
        return

    all_trainings = fetch_monthly_trainings()
    if not all_trainings:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="⚠️ Eğitim takvimi verilerine ulaşılamadı. Lütfen daha sonra tekrar deneyin.",
        )
        return

    my_trainings = filter_trainings(all_trainings, month_name, department)

    dept_display = DEPT_DISPLAY_NAMES.get(department, department)

    builder = MessageBuilder()
    builder.add_header(f"📅 {month_name} — Eğitim Takvimin")
    builder.add_text(f"Bölümün: *{dept_display}*")
    builder.add_divider()

    if not my_trainings:
        builder.add_text(f"🎉 _{month_name}_ ayında bölümüne atanmış bir eğitim bulunmuyor.")
    else:
        required = []
        recommended = []
        optional = []

        for t in my_trainings:
            if "olmalı" in t["durum"]:
                required.append(t)
            elif "önerilir" in t["durum"]:
                recommended.append(t)
            else:
                optional.append(t)

        if required:
            builder.add_text("*📌 Zorunlu Eğitimler*")
            for t in required:
                builder.add_text(f"  • {t['egitim']}\n    _{t['durum']}_")

        if recommended:
            if required:
                builder.add_divider()
            builder.add_text("*💡 Önerilen Eğitimler*")
            for t in recommended:
                builder.add_text(f"  • {t['egitim']}\n    _{t['durum']}_")

        if optional:
            if required or recommended:
                builder.add_divider()
            builder.add_text("*📎 Diğer Eğitimler*")
            for t in optional:
                builder.add_text(f"  • {t['egitim']}\n    _{t['durum']}_")

    builder.add_divider()
    builder.add_context([
        f"📆 {month_name} {now.year}  •  Bölüm: {dept_display}  •  /this-month"
    ])

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"📅 {month_name} — Eğitim Takvimin",
        blocks=builder.build(),
    )
    _logger.info(
        "[CMD] /this-month: user=%s dept=%s month=%s trainings=%d",
        user_id, department, month_name, len(my_trainings),
    )
