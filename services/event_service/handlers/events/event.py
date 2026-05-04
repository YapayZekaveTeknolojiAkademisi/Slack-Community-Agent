"""
Event Service — Modal submission ve buton action handler'lari.
"""
from __future__ import annotations

import json
from datetime import datetime, time, timezone

from slack_bolt import Ack, App
from sqlalchemy import select

from packages.database.manager import db
from packages.database.models.event import Event, EventInterest, EventStatus, LocationType
from packages.database.repository.event import EventRepository, EventInterestRepository
from packages.settings import get_settings
from packages.slack.client import slack_client
from ...logger import _logger
from ...utils.notifications import (
    post_admin_request, post_announcement, post_update_announcement, send_dm,
)
from ...utils.email import send_admin_notification, send_user_status_email
from ...utils.calendar import build_google_calendar_url
from ...utils.notifications import _location_display
from packages.slack.blocks.builder import MessageBuilder

app: App = slack_client.app
settings = get_settings()


def _run_async(coro, timeout=30.0):
    from services.event_service.core.event_loop import run_async
    return run_async(coro, timeout=timeout)


def _extract_form_values(values: dict) -> dict:
    """Modal form degerlerini cikarir."""
    location_type = values.get("event_location", {}).get("val", {}).get("selected_option", {}).get("value", "other")
    return {
        "name": values.get("event_name", {}).get("val", {}).get("value", ""),
        "topic": values.get("event_topic", {}).get("val", {}).get("value", ""),
        "description": values.get("event_description", {}).get("val", {}).get("value", ""),
        "date": values.get("event_date", {}).get("val", {}).get("selected_date"),
        "time": values.get("event_time", {}).get("val", {}).get("selected_time"),
        "duration_minutes": int(values.get("event_duration", {}).get("val", {}).get("selected_option", {}).get("value", "60")),
        "location_type": LocationType(location_type),
        "channel_id": values.get("event_channel", {}).get("val", {}).get("selected_channel"),
        "link": values.get("event_link", {}).get("val", {}).get("value"),
        "yzta_request": values.get("event_yzta", {}).get("val", {}).get("value"),
    }


def _validate_form(data: dict) -> str | None:
    """Backend validasyonu. Hata mesaji doner, gecerliyse None."""
    if data["location_type"] == LocationType.SLACK_CHANNEL and not data.get("channel_id"):
        return "Slack Kanalı seçildiğinde kanal alanı zorunludur."
    if data["location_type"] != LocationType.SLACK_CHANNEL and not data.get("link"):
        return "Harici platform seçildiğinde link alanı zorunludur."
    if not data.get("date") or not data.get("time"):
        return "Tarih ve saat zorunludur."
    return None


# ---------------------------------------------------------------------------
# event_create_modal
# ---------------------------------------------------------------------------

@app.view("event_create_modal")
def handle_create_modal(ack: Ack, body: dict, client, view):
    user_id = body["user"]["id"]
    values = view["state"]["values"]
    data = _extract_form_values(values)

    error = _validate_form(data)
    if error:
        ack(response_action="errors", errors={"event_location": error})
        return
    ack()

    evt_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
    evt_time = datetime.strptime(data["time"], "%H:%M").time()

    async def _create():
        async with db.session() as session:
            event = Event(
                creator_slack_id=user_id,
                name=data["name"],
                topic=data["topic"],
                description=data["description"],
                date=evt_date,
                time=evt_time,
                duration_minutes=data["duration_minutes"],
                location_type=data["location_type"],
                channel_id=data.get("channel_id"),
                link=data.get("link"),
                yzta_request=data.get("yzta_request"),
                status=EventStatus.PENDING,
            )
            session.add(event)
            await session.flush()
            return event

    try:
        event = _run_async(_create())
    except Exception as e:
        _logger.error("[EVT] Create failed: %s", e)
        return

    post_admin_request(event)
    send_admin_notification(event)

    loc = _location_display(event)
    confirm_text = (
        f"Etkinlik talebiniz başarıyla iletildi!\n\n"
        f"*{event.name}*\n"
        f"{event.date.strftime('%d %B %Y')} · {event.time.strftime('%H:%M')} · {loc}\n\n"
        f"Admin onayını bekliyor. Sonuç Slack DM ve e-posta ile bildirilecek.\n"
        f"_Talep ID: {event.id}_"
    )
    send_dm(user_id, confirm_text)

    _logger.info("[EVT] Event created: %s by %s", event.id, user_id)


# ---------------------------------------------------------------------------
# event_update_select_modal (1. adim — etkinlik secimi)
# ---------------------------------------------------------------------------

@app.view("event_update_select_modal")
def handle_update_select_modal(ack: Ack, body: dict, client, view):
    """Guncelleme icin etkinlik secildiginde 2. modal'i (guncelleme formu) acar."""
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    event_id = values.get("update_event_select", {}).get("val", {}).get("selected_option", {}).get("value")

    if not event_id:
        return

    is_admin = user_id in settings.slack_admins

    async def _fetch():
        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            return await repo.get(event_id)

    try:
        evt = _run_async(_fetch())
    except Exception as e:
        _logger.error("[EVT] update select fetch failed: %s", e)
        return

    if not evt or evt.status != EventStatus.APPROVED:
        return
    if evt.creator_slack_id != user_id and not is_admin:
        return

    # Mevcut degerlerle 2. modal'i ac
    from ...handlers.commands.event import _build_event_form_blocks
    loc_val = evt.location_type.value if isinstance(evt.location_type, LocationType) else evt.location_type
    initial = {
        "name": evt.name,
        "topic": evt.topic,
        "description": evt.description,
        "date": evt.date.isoformat(),
        "time": evt.time.strftime("%H:%M"),
        "duration": str(evt.duration_minutes),
        "location_type": loc_val,
        "channel_id": evt.channel_id,
        "link": evt.link,
        "yzta_request": evt.yzta_request,
    }
    blocks = _build_event_form_blocks(initial)

    # Slack views_open yerine views_push kullanarak 2. modal'i acariz
    # Ancak views_push sadece mevcut modal acikken calisir — view submission sonrasi
    # modal kapanir, bu yuzden response_action ile update yapamayiz.
    # Cozum: views_open ile yeni modal acariz.
    try:
        # trigger_id view submission'da body'den gelir
        trigger_id = body.get("trigger_id")
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "event_update_modal",
                "private_metadata": json.dumps({"event_id": event_id}),
                "title": {"type": "plain_text", "text": "Etkinlik Güncelle"},
                "submit": {"type": "plain_text", "text": "Güncelle"},
                "close": {"type": "plain_text", "text": "İptal"},
                "blocks": blocks,
            },
        )
    except Exception as e:
        _logger.error("[EVT] Could not open update form modal: %s", e)


# ---------------------------------------------------------------------------
# event_update_modal (2. adim — guncelleme formu)
# ---------------------------------------------------------------------------

@app.view("event_update_modal")
def handle_update_modal(ack: Ack, body: dict, client, view):
    user_id = body["user"]["id"]
    meta = json.loads(view.get("private_metadata") or "{}")
    event_id = meta.get("event_id")
    if not event_id:
        ack()
        return

    values = view["state"]["values"]
    data = _extract_form_values(values)

    error = _validate_form(data)
    if error:
        ack(response_action="errors", errors={"event_location": error})
        return
    ack()

    evt_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
    evt_time = datetime.strptime(data["time"], "%H:%M").time()

    async def _update():
        async with db.session() as session:
            repo = EventRepository(session)
            evt = await repo.get(event_id)
            if not evt or evt.status != EventStatus.APPROVED:
                return None, {}

            old_values = {
                "name": evt.name, "topic": evt.topic, "description": evt.description,
                "date": str(evt.date), "time": str(evt.time),
                "duration_minutes": evt.duration_minutes,
                "location_type": evt.location_type, "channel_id": evt.channel_id,
                "link": evt.link, "yzta_request": evt.yzta_request,
            }

            evt.name = data["name"]
            evt.topic = data["topic"]
            evt.description = data["description"]
            evt.date = evt_date
            evt.time = evt_time
            evt.duration_minutes = data["duration_minutes"]
            evt.location_type = data["location_type"]
            evt.channel_id = data.get("channel_id")
            evt.link = data.get("link")
            evt.yzta_request = data.get("yzta_request")
            await session.flush()

            new_values = {
                "name": evt.name, "topic": evt.topic, "description": evt.description,
                "date": str(evt.date), "time": str(evt.time),
                "duration_minutes": evt.duration_minutes,
                "location_type": evt.location_type, "channel_id": evt.channel_id,
                "link": evt.link, "yzta_request": evt.yzta_request,
            }
            diff = {k: (old_values[k], new_values[k]) for k in old_values if old_values[k] != new_values[k]}
            return evt, diff

    try:
        evt, diff = _run_async(_update())
    except Exception as e:
        _logger.error("[EVT] Update failed: %s", e)
        return

    if not evt:
        return

    if not diff:
        return

    field_labels = {
        "name": "Ad", "topic": "Konu", "description": "Açıklama",
        "date": "Tarih", "time": "Saat", "duration_minutes": "Süre",
        "location_type": "Lokasyon", "channel_id": "Kanal", "link": "Link",
        "yzta_request": "YZTA Talep",
    }
    diff_lines = []
    for k, (old, new) in diff.items():
        label = field_labels.get(k, k)
        old_display = old or "—"
        diff_lines.append(f"*{label}:* ~{old_display}~ → *{new}*")

    diff_text = (
        f"Etkinlik Güncellendi\n\n"
        f"*{evt.name}*\n"
        f"*Güncelleyen:* <@{user_id}>\n\n"
        f"*Değişen Alanlar:*\n" + "\n".join(diff_lines) + f"\n\n_{evt.id}_"
    )
    try:
        slack_client.bot_client.chat_postMessage(
            channel=settings.slack_admin_channel, text=diff_text,
        )
    except Exception as e:
        _logger.error("[EVT] Admin update notification failed: %s", e)

    post_update_announcement(evt)

    # Ilgi gosterenlere guncelleme e-postasi
    async def _notify_interested():
        async with db.session(read_only=True) as session:
            interest_repo = EventInterestRepository(session)
            interests = await interest_repo.list_by_event(event_id)
            return [i.slack_id for i in interests]

    try:
        interested_ids = _run_async(_notify_interested())
        from ...utils.email import send_update_email
        for sid in interested_ids:
            send_update_email(sid, evt)
    except Exception as e:
        _logger.warning("[EVT] Update email notifications failed: %s", e)

    _logger.info("[EVT] Event updated: %s by %s diff=%s", event_id, user_id, list(diff.keys()))


# ---------------------------------------------------------------------------
# Admin Onay/Red butonlari
# ---------------------------------------------------------------------------

@app.action("event_approve_btn")
def handle_approve_btn(ack: Ack, body: dict, client, action):
    ack()
    event_id = action.get("value")
    trigger_id = body.get("trigger_id")
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "event_admin_approve_modal",
            "private_metadata": event_id,
            "title": {"type": "plain_text", "text": "Etkinlik Onayla"},
            "submit": {"type": "plain_text", "text": "Onayla"},
            "close": {"type": "plain_text", "text": "İptal"},
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"Etkinlik *{event_id}* onaylanacak."}},
                {"type": "input", "block_id": "admin_note", "optional": True,
                 "element": {"type": "plain_text_input", "action_id": "val", "multiline": True,
                             "placeholder": {"type": "plain_text", "text": "Varsa eklemek istediğiniz notu yazın..."}},
                 "label": {"type": "plain_text", "text": "Not (opsiyonel)"}},
            ],
        },
    )


@app.action("event_reject_btn")
def handle_reject_btn(ack: Ack, body: dict, client, action):
    ack()
    event_id = action.get("value")
    trigger_id = body.get("trigger_id")
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "event_admin_reject_modal",
            "private_metadata": event_id,
            "title": {"type": "plain_text", "text": "Etkinlik Reddet"},
            "submit": {"type": "plain_text", "text": "Reddet"},
            "close": {"type": "plain_text", "text": "İptal"},
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"Etkinlik *{event_id}* reddedilecek."}},
                {"type": "input", "block_id": "admin_note", "optional": True,
                 "element": {"type": "plain_text_input", "action_id": "val", "multiline": True,
                             "placeholder": {"type": "plain_text", "text": "Varsa eklemek istediğiniz notu yazın..."}},
                 "label": {"type": "plain_text", "text": "Not (opsiyonel)"}},
            ],
        },
    )


@app.view("event_admin_approve_modal")
def handle_admin_approve(ack: Ack, body: dict, client, view):
    ack()
    event_id = view.get("private_metadata")
    admin_id = body["user"]["id"]
    note = view["state"]["values"].get("admin_note", {}).get("val", {}).get("value")

    async def _approve():
        async with db.session() as session:
            repo = EventRepository(session)
            evt = await repo.get(event_id)
            if not evt or evt.status != EventStatus.PENDING:
                return None
            evt.status = EventStatus.APPROVED
            evt.approved_by = admin_id
            if note:
                evt.admin_note = note
            await session.flush()
            return evt

    evt = _run_async(_approve())
    if not evt:
        return

    note_text = f"\n*Admin Notu:* {note}" if note else ""
    loc = _location_display(evt)
    send_dm(
        evt.creator_slack_id,
        f"Etkinliğiniz Onaylandı!\n\n"
        f"*{evt.name}*\n"
        f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}"
        f"{note_text}\n\n"
        f"Duyuru #serbest-kürsü kanalına gönderildi.\n_{evt.id}_"
    )

    send_user_status_email(evt.creator_slack_id, evt, "approved", note)
    post_announcement(evt)

    _logger.info("[EVT] Event approved: %s by admin %s", event_id, admin_id)


@app.view("event_admin_reject_modal")
def handle_admin_reject(ack: Ack, body: dict, client, view):
    ack()
    event_id = view.get("private_metadata")
    admin_id = body["user"]["id"]
    note = view["state"]["values"].get("admin_note", {}).get("val", {}).get("value")

    async def _reject():
        async with db.session() as session:
            repo = EventRepository(session)
            evt = await repo.get(event_id)
            if not evt or evt.status != EventStatus.PENDING:
                return None
            evt.status = EventStatus.REJECTED
            if note:
                evt.admin_note = note
            await session.flush()
            return evt

    evt = _run_async(_reject())
    if not evt:
        return

    note_text = f"\n*Admin Notu:* {note}" if note else ""
    send_dm(
        evt.creator_slack_id,
        f"Etkinliğiniz Reddedildi\n\n"
        f"*{evt.name}*\n"
        f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')}"
        f"{note_text}\n\n"
        f"Yeni bir etkinlik talebi için `/event create` komutunu kullanabilirsiniz.\n_{evt.id}_"
    )

    send_user_status_email(evt.creator_slack_id, evt, "rejected", note)

    _logger.info("[EVT] Event rejected: %s by admin %s", event_id, admin_id)


# ---------------------------------------------------------------------------
# Katilacagim butonu
# ---------------------------------------------------------------------------

@app.action("event_interest_btn")
def handle_interest_btn(ack: Ack, body: dict, client, action):
    ack()
    event_id = action.get("value")
    user_id = body["user"]["id"]
    channel_id = body.get("channel", {}).get("id", "")

    async def _add_interest():
        async with db.session() as session:
            repo = EventRepository(session)
            evt = await repo.get(event_id)
            if not evt or evt.status != EventStatus.APPROVED:
                return None, "not_found", 0
            interest_repo = EventInterestRepository(session)
            existing = await interest_repo.find_by_event_and_user(event_id, user_id)
            if existing:
                count = await interest_repo.count_by_event(event_id)
                return evt, "already", count
            await interest_repo.create(EventInterest(event_id=event_id, slack_id=user_id))
            count = await interest_repo.count_by_event(event_id)
            return evt, "ok", count

    try:
        evt, result, count = _run_async(_add_interest())
    except Exception as e:
        _logger.error("[EVT] Interest button failed: %s", e)
        return

    if result == "not_found":
        client.chat_postEphemeral(channel=channel_id, user=user_id,
                                   text="Etkinlik bulunamadı veya ilgi gösterilemez durumda.")
        return

    from ...utils.notifications import _calendar_url, _location_with_link_inline
    loc = _location_with_link_inline(evt)

    if result == "already":
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text=(
                f"Bu etkinliğe zaten ilgi gösterdiniz!\n"
                f"───\n"
                f"*{evt.name}*\n"
                f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n"
                f"{evt.description}\n"
                f"<@{evt.creator_slack_id}>  · {count} ilgili · ✓ ilgi gösterdin\n"
                f"Etkinlik günü hatırlatma e-postası alacaksın."
            ),
        )
        return

    # Basarili — ephemeral
    client.chat_postEphemeral(
        channel=channel_id, user=user_id,
        text=(
            f"İlgin kaydedildi!\n"
            f"───\n"
            f"*{evt.name}*\n"
            f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n"
            f"{evt.description}\n"
            f"<@{evt.creator_slack_id}>  · {count} ilgili · ✓ ilgi gösterdin\n"
            f"Etkinlik günü hatırlatma e-postası alacaksın."
        ),
    )

    # DM
    cal_url = _calendar_url(evt)
    dm_builder = MessageBuilder()
    dm_builder.add_text(
        f"İlgin kaydedildi!\n\n"
        f"*{evt.name}*\n"
        f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n\n"
        f"Etkinlik günü hatırlatma e-postası alacaksın.\n_{evt.id}_"
    )
    dm_builder.add_button("Google Takvime Ekle", "event_calendar_btn", value=evt.id, url=cal_url)
    send_dm(user_id, f"İlgin kaydedildi: {evt.name}", dm_builder.build())

    _logger.info("[EVT] Interest added: event=%s user=%s", event_id, user_id)


@app.action("event_calendar_btn")
def handle_calendar_btn(ack: Ack, body: dict, client, action):
    ack()


# ---------------------------------------------------------------------------
# Iptal modal submission
# ---------------------------------------------------------------------------

@app.view("event_cancel_modal")
def handle_cancel_modal(ack: Ack, body: dict, client, view):
    """Iptal formu gonderildiginde calisir."""
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    event_id = values.get("cancel_event_select", {}).get("val", {}).get("selected_option", {}).get("value")

    if not event_id:
        return

    is_admin = user_id in settings.slack_admins

    async def _cancel():
        async with db.session() as session:
            repo = EventRepository(session)
            evt = await repo.get(event_id)
            if not evt or evt.status != EventStatus.APPROVED:
                return None
            if evt.creator_slack_id != user_id and not is_admin:
                return None
            evt.status = EventStatus.CANCELLED
            await session.flush()
            return evt

    try:
        evt = _run_async(_cancel())
    except Exception as e:
        _logger.error("[EVT] Cancel failed: %s", e)
        return

    if not evt:
        return

    # Duyuru kanallarina iptal bildirisi
    from ...utils.notifications import post_cancellation, send_dm as _send_dm
    post_cancellation(evt, user_id)

    # Admin kanalina iptal bildirimi
    try:
        slack_client.bot_client.chat_postMessage(
            channel=settings.slack_admin_channel,
            text=(
                f"Etkinlik İptal Edildi\n\n"
                f"*{evt.name}*\n"
                f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')}\n"
                f"*Düzenleyen:* <@{evt.creator_slack_id}>\n"
                f"*İptal Eden:* <@{user_id}>"
            ),
        )
    except Exception as e:
        _logger.warning("[EVT] Admin cancel notification failed: %s", e)

    # Kullaniciya DM ile onay
    _send_dm(
        user_id,
        f"Etkinlik başarıyla iptal edildi.\n*{evt.name}*\n"
        f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')}"
    )

    # Admin iptal ettiyse sahibe DM
    if is_admin and evt.creator_slack_id != user_id:
        _send_dm(
            evt.creator_slack_id,
            f"Etkinliğiniz admin tarafından iptal edildi.\n*{evt.name}*"
        )

    # Ilgi gosterenlere iptal e-postasi
    async def _notify_interested():
        async with db.session(read_only=True) as session:
            interest_repo = EventInterestRepository(session)
            interests = await interest_repo.list_by_event(event_id)
            return [i.slack_id for i in interests]

    try:
        interested_ids = _run_async(_notify_interested())
        from ...utils.email import send_cancellation_email
        for sid in interested_ids:
            send_cancellation_email(sid, evt)
    except Exception as e:
        _logger.warning("[EVT] Cancel email notifications failed: %s", e)

    _logger.info("[EVT] Event cancelled via modal: %s by %s", event_id, user_id)


# ---------------------------------------------------------------------------
# Ilgi gosterme modal submission
# ---------------------------------------------------------------------------

@app.view("event_add_me_modal")
def handle_add_me_modal(ack: Ack, body: dict, client, view):
    """/event add_me formu gonderildiginde calisir."""
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    event_id = values.get("add_me_event_select", {}).get("val", {}).get("selected_option", {}).get("value")

    # Kanal bilgisini private_metadata'dan oku (ephemeral mesaj icin)
    channel_id: str | None = None
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
        channel_id = meta.get("channel_id")
    except Exception:
        channel_id = None

    if not event_id:
        return

    async def _add():
        async with db.session() as session:
            repo = EventRepository(session)
            evt = await repo.get(event_id)
            if not evt or evt.status != EventStatus.APPROVED:
                return None, "not_found", 0
            interest_repo = EventInterestRepository(session)
            existing = await interest_repo.find_by_event_and_user(event_id, user_id)
            if existing:
                count = await interest_repo.count_by_event(event_id)
                return evt, "already", count
            await interest_repo.create(EventInterest(event_id=event_id, slack_id=user_id))
            count = await interest_repo.count_by_event(event_id)
            return evt, "ok", count

    try:
        evt, status, count = _run_async(_add())
    except Exception as e:
        _logger.error("[EVT] add_me modal failed: %s", e)
        send_dm(user_id, "İlgi kaydedilemedi, tekrar deneyin.")
        return

    if status == "not_found":
        send_dm(user_id, "Etkinlik bulunamadı veya ilgi gösterilemez durumda.")
        return

    from ...utils.notifications import _calendar_url, _location_with_link_inline
    loc = _location_with_link_inline(evt)

    if status == "already":
        already_text = (
            f"Bu etkinliğe zaten ilgi gösterdiniz!\n"
            f"───\n"
            f"*{evt.name}*\n"
            f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n"
            f"{evt.description}\n"
            f"<@{evt.creator_slack_id}>  · {count} ilgili · ✓ ilgi gösterdin\n"
            f"Etkinlik günü hatırlatma e-postası alacaksın."
        )
        if channel_id:
            try:
                client.chat_postEphemeral(channel=channel_id, user=user_id, text=already_text)
            except Exception:
                pass
        send_dm(user_id, already_text)
        return

    # Basarili
    success_text = (
        f"İlgin kaydedildi!\n"
        f"───\n"
        f"*{evt.name}*\n"
        f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n"
        f"{evt.description}\n"
        f"<@{evt.creator_slack_id}>  · {count} ilgili · ✓ ilgi gösterdin\n"
        f"Etkinlik günü hatırlatma e-postası alacaksın."
    )

    # 1) Komutun yazildigi kanala ephemeral onay
    if channel_id:
        try:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text=success_text)
        except Exception as e:
            _logger.warning("[EVT] add_me ephemeral gonderilemedi: %s", e)

    # 2) DM (tam detay + Google Takvime Ekle butonu)
    cal_url = _calendar_url(evt)
    dm_builder = MessageBuilder()
    dm_builder.add_text(
        f"İlgin kaydedildi!\n\n"
        f"*{evt.name}*\n"
        f"{evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n\n"
        f"Etkinlik günü hatırlatma e-postası alacaksın.\n_{evt.id}_"
    )
    dm_builder.add_button("Google Takvime Ekle", "event_calendar_btn", value=evt.id, url=cal_url)
    send_dm(user_id, f"İlgin kaydedildi: {evt.name}", dm_builder.build())

    _logger.info("[EVT] Interest added via modal: event=%s user=%s", event_id, user_id)
