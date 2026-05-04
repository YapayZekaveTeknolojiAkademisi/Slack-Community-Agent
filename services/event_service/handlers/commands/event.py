"""
Event Service — /event komutu router ve basit alt komutlar.
"""
from __future__ import annotations

from datetime import date

from slack_bolt import Ack, App

from packages.database.manager import db
from packages.database.models.event import Event, EventInterest, EventStatus
from packages.database.repository.event import EventRepository, EventInterestRepository
from packages.settings import get_settings
from packages.slack.blocks.builder import MessageBuilder, BlockBuilder
from packages.slack.client import slack_client
from ...logger import _logger
from ...utils.calendar import build_google_calendar_url
from ...utils.notifications import _location_display

app: App = slack_client.app
settings = get_settings()


def _run_async(coro, timeout=30.0):
    """Bolt handler thread'inden async kodu calistirmak icin."""
    from services.event_service.core.event_loop import run_async
    return run_async(coro, timeout=timeout)


# ---------------------------------------------------------------------------
# /event command router
# ---------------------------------------------------------------------------

@app.command("/event")
def handle_event_command(ack: Ack, body: dict, client, command):
    ack()

    user_id = body.get("user_id")
    channel_id = body.get("channel_id", "")
    args = body.get("text", "").strip().split()
    cmd = args[0].lower() if args else "help"

    # Kanal kontrolu — sadece event_channel'da calisir
    if channel_id != settings.event_channel:
        client.chat_postMessage(
            channel=user_id,
            text=f"Bu komut sadece <#{settings.event_channel}> kanalında kullanılabilir."
        )
        return

    if cmd == "create":
        _open_create_modal(client, body.get("trigger_id"), user_id)
    elif cmd == "list":
        _handle_list(client, user_id, channel_id)
    elif cmd == "my_list":
        _handle_my_list(client, user_id, channel_id)
    elif cmd == "history":
        _handle_history(client, user_id, channel_id)
    elif cmd == "add_me":
        _handle_add_me(client, body, user_id, channel_id)
    elif cmd == "update":
        _handle_update(client, body, user_id, channel_id)
    elif cmd == "cancel":
        _handle_cancel(client, body, user_id, channel_id)
    elif cmd == "help":
        _handle_help(client, user_id, channel_id)
    else:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="Bilinmeyen komut. `/event help` ile kullanılabilir komutları görün."
        )


# ---------------------------------------------------------------------------
# /event create — Modal acma
# ---------------------------------------------------------------------------

DURATION_OPTIONS = [
    {"label": "30 dakika", "value": "30"},
    {"label": "1 saat", "value": "60"},
    {"label": "1.5 saat", "value": "90"},
    {"label": "2 saat", "value": "120"},
    {"label": "3 saat", "value": "180"},
]

LOCATION_OPTIONS = [
    {"label": "Slack Kanalı", "value": "slack_channel"},
    {"label": "Zoom", "value": "zoom"},
    {"label": "YouTube", "value": "youtube"},
    {"label": "Google Meet", "value": "google_meet"},
    {"label": "Discord", "value": "discord"},
    {"label": "Diğer", "value": "other"},
]


def _build_event_form_blocks(initial: dict | None = None) -> list[dict]:
    """Event form bloklarini olusturur. initial verilirse update icin dolu gelir."""
    iv = initial or {}
    blocks = []

    # 1. Etkinlik Adi
    name_elem = {"type": "plain_text_input", "action_id": "val",
                 "placeholder": {"type": "plain_text", "text": "Örn: Python ile Web Scraping Workshop"}}
    if iv.get("name"):
        name_elem["initial_value"] = iv["name"]
    blocks.append({"type": "input", "block_id": "event_name", "element": name_elem,
                    "label": {"type": "plain_text", "text": "Etkinlik Adı"}})

    # 2. Konu
    topic_elem = {"type": "plain_text_input", "action_id": "val",
                  "placeholder": {"type": "plain_text", "text": "Örn: Web Scraping, Veri Analizi"}}
    if iv.get("topic"):
        topic_elem["initial_value"] = iv["topic"]
    blocks.append({"type": "input", "block_id": "event_topic", "element": topic_elem,
                    "label": {"type": "plain_text", "text": "Konu"}})

    # 3. Aciklama & Amac
    desc_elem = {"type": "plain_text_input", "action_id": "val", "multiline": True,
                 "placeholder": {"type": "plain_text", "text": "Etkinliğin amacını ve katılımcılara neler katacağını açıklayın..."}}
    if iv.get("description"):
        desc_elem["initial_value"] = iv["description"]
    blocks.append({"type": "input", "block_id": "event_description", "element": desc_elem,
                    "label": {"type": "plain_text", "text": "Açıklama & Amaç"}})

    # 4. Tarih
    date_elem = {"type": "datepicker", "action_id": "val",
                 "placeholder": {"type": "plain_text", "text": "Tarih seçin..."}}
    if iv.get("date"):
        date_elem["initial_date"] = iv["date"]
    blocks.append({"type": "input", "block_id": "event_date", "element": date_elem,
                    "label": {"type": "plain_text", "text": "Tarih"}})

    # 5. Saat
    time_elem = {"type": "timepicker", "action_id": "val",
                 "placeholder": {"type": "plain_text", "text": "Saat seçin..."}}
    if iv.get("time"):
        time_elem["initial_time"] = iv["time"]
    blocks.append({"type": "input", "block_id": "event_time", "element": time_elem,
                    "label": {"type": "plain_text", "text": "Saat"}})

    # 6. Sure
    dur_opts = [{"text": {"type": "plain_text", "text": o["label"]}, "value": o["value"]} for o in DURATION_OPTIONS]
    dur_elem = {"type": "static_select", "action_id": "val",
                "placeholder": {"type": "plain_text", "text": "Süre seçin..."}, "options": dur_opts}
    if iv.get("duration"):
        for o in dur_opts:
            if o["value"] == iv["duration"]:
                dur_elem["initial_option"] = o
                break
    blocks.append({"type": "input", "block_id": "event_duration", "element": dur_elem,
                    "label": {"type": "plain_text", "text": "Tahmini Süre"}})

    # 7. Etkinlik Lokasyonu
    loc_opts = [{"text": {"type": "plain_text", "text": o["label"]}, "value": o["value"]} for o in LOCATION_OPTIONS]
    loc_elem = {"type": "static_select", "action_id": "val",
                "placeholder": {"type": "plain_text", "text": "Lokasyon seçin..."}, "options": loc_opts}
    if iv.get("location_type"):
        for o in loc_opts:
            if o["value"] == iv["location_type"]:
                loc_elem["initial_option"] = o
                break
    blocks.append({"type": "input", "block_id": "event_location", "element": loc_elem,
                    "label": {"type": "plain_text", "text": "Etkinlik Lokasyonu"}})

    # 8. Slack Kanali (opsiyonel — backend'de validate edilir)
    ch_elem = {"type": "channels_select", "action_id": "val",
               "placeholder": {"type": "plain_text", "text": "Kanal seçin..."}}
    if iv.get("channel_id"):
        ch_elem["initial_channel"] = iv["channel_id"]
    blocks.append({"type": "input", "block_id": "event_channel", "optional": True, "element": ch_elem,
                    "label": {"type": "plain_text", "text": "Slack Kanalı (lokasyon Slack ise zorunlu)"}})

    # 9. Etkinlik Linki (opsiyonel — backend'de validate edilir)
    link_elem = {"type": "url_text_input", "action_id": "val",
                 "placeholder": {"type": "plain_text", "text": "Örn: https://zoom.us/j/123 veya Drive linki"}}
    link_val = iv.get("link")
    if link_val and isinstance(link_val, str) and (link_val.startswith("http://") or link_val.startswith("https://")):
        link_elem["initial_value"] = link_val
    blocks.append({"type": "input", "block_id": "event_link", "optional": True, "element": link_elem,
                    "label": {"type": "plain_text", "text": "Etkinlik Linki (harici platform ise zorunlu)"}})

    # 10. YZTA'dan Beklenen (opsiyonel)
    yzta_elem = {"type": "plain_text_input", "action_id": "val", "multiline": True,
                 "placeholder": {"type": "plain_text", "text": "Organizasyondan bir destek veya kaynak talebiniz varsa belirtin..."}}
    if iv.get("yzta_request"):
        yzta_elem["initial_value"] = iv["yzta_request"]
    blocks.append({"type": "input", "block_id": "event_yzta", "optional": True, "element": yzta_elem,
                    "label": {"type": "plain_text", "text": "YZTA'dan Beklenen (opsiyonel)"}})

    return blocks


def _open_create_modal(client, trigger_id: str, user_id: str) -> None:
    blocks = _build_event_form_blocks()
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "event_create_modal",
            "title": {"type": "plain_text", "text": "Yeni Etkinlik Oluştur"},
            "submit": {"type": "plain_text", "text": "Gönder"},
            "close": {"type": "plain_text", "text": "İptal"},
            "blocks": blocks,
        },
    )


# ---------------------------------------------------------------------------
# /event list
# ---------------------------------------------------------------------------

def _handle_list(client, user_id: str, channel_id: str) -> None:
    from ...utils.notifications import _location_with_link_inline

    async def _fetch():
        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            events = await repo.list_current_month()
            interest_repo = EventInterestRepository(session)
            # Kullanicinin ilgi gosterdigi event ID'lerini tek sorguyla al (N+1 onleme)
            user_interest_ids = await interest_repo.set_event_ids_by_user(user_id)
            # Tarihsel sira (ASC): en yakin tarih once
            events = sorted(events, key=lambda e: (e.date, e.time))
            result = []
            for evt in events:
                count = await interest_repo.count_by_event(evt.id)
                result.append((evt, count))
            return result, user_interest_ids

    try:
        items, user_interest_ids = _run_async(_fetch())
    except Exception as e:
        _logger.error("[CMD] list failed: %s", e)
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="Etkinlikler yüklenemedi.")
        return

    builder = MessageBuilder()
    builder.add_header("Bu Ayın Etkinlikleri")

    if not items:
        builder.add_text("_Bu ay henüz onaylanmış etkinlik yok._")
    else:
        from ...utils.notifications import _calendar_url
        builder.add_divider()
        for evt, count in items:
            loc = _location_with_link_inline(evt)
            interested_marker = " · ✓ ilgi gösterdin" if evt.id in user_interest_ids else ""
            line = (
                f"• *{evt.name}*\n"
                f"  {evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n"
                f"  {evt.description}\n"
                f"  <@{evt.creator_slack_id}>  · {count} ilgili{interested_marker}"
            )
            builder.add_text(line)
            cal_url = _calendar_url(evt)
            builder.add_button("Katılacağım", "event_interest_btn", value=evt.id, style="primary")
            builder.add_button("Google Takvime Ekle", "event_calendar_btn", value=evt.id, url=cal_url)
            builder.add_divider()
        builder.add_context([f"Toplam: {len(items)} etkinlik"])

    client.chat_postEphemeral(channel=channel_id, user=user_id, text="Bu Ayın Etkinlikleri", blocks=builder.build())


# ---------------------------------------------------------------------------
# /event my_list
# ---------------------------------------------------------------------------

def _handle_my_list(client, user_id: str, channel_id: str) -> None:
    from ...utils.notifications import _location_with_link_inline

    STATUS_LABELS = {
        "pending": "Onay Bekliyor",
        "approved": "Onaylandı",
        "rejected": "Reddedildi",
        "cancelled": "İptal Edildi",
        "completed": "Gerçekleşti",
    }

    async def _fetch():
        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            events = await repo.list_by_creator(user_id)
            interest_repo = EventInterestRepository(session)
            user_interest_ids = await interest_repo.set_event_ids_by_user(user_id)
            result = []
            for evt in events:
                count = await interest_repo.count_by_event(evt.id)
                result.append((evt, count))
            return result, user_interest_ids

    try:
        items, user_interest_ids = _run_async(_fetch())
    except Exception as e:
        _logger.error("[CMD] my_list failed: %s", e)
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="Etkinlikler yüklenemedi.")
        return

    builder = MessageBuilder()
    builder.add_header("Etkinliklerim")

    if not items:
        builder.add_text("_Henüz etkinlik oluşturmadınız._")
    else:
        builder.add_divider()
        for evt, count in items:
            loc = _location_with_link_inline(evt)
            status_label = STATUS_LABELS.get(evt.status.value, evt.status.value)
            interested_marker = " · ✓ ilgi gösterdin" if evt.id in user_interest_ids else ""
            line = (
                f"• *{evt.name}*\n"
                f"  {evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n"
                f"  {evt.description}\n"
                f"  <@{evt.creator_slack_id}>  · {count} ilgili{interested_marker}\n"
                f"  _{status_label}_"
            )
            builder.add_text(line)
        builder.add_divider()
        builder.add_context([f"Toplam: {len(items)} etkinlik"])

    client.chat_postEphemeral(channel=channel_id, user=user_id, text="Etkinliklerim", blocks=builder.build())


# ---------------------------------------------------------------------------
# /event history
# ---------------------------------------------------------------------------

def _handle_history(client, user_id: str, channel_id: str) -> None:
    from ...utils.notifications import _location_with_link_inline

    STATUS_LABELS = {
        "completed": "Gerçekleşti",
        "cancelled": "İptal Edildi",
    }

    async def _fetch():
        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            events = await repo.list_history()
            interest_repo = EventInterestRepository(session)
            # Kullanicinin ilgi gosterdigi event ID'lerini tek sorguyla al (N+1 onleme)
            user_interest_ids = await interest_repo.set_event_ids_by_user(user_id)
            # Tarihsel sira (DESC): en yeni tarih once
            events = sorted(events, key=lambda e: (e.date, e.time), reverse=True)
            result = []
            for evt in events:
                count = await interest_repo.count_by_event(evt.id)
                result.append((evt, count))
            return result, user_interest_ids

    try:
        items, user_interest_ids = _run_async(_fetch())
    except Exception as e:
        _logger.error("[CMD] history failed: %s", e)
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="Geçmiş yüklenemedi.")
        return

    builder = MessageBuilder()
    builder.add_header("Geçmiş Etkinlikler")

    if not items:
        builder.add_text("_Henüz geçmiş etkinlik yok._")
    else:
        builder.add_divider()
        for evt, count in items:
            loc = _location_with_link_inline(evt)
            interested_marker = " · ✓ ilgi gösterdin" if evt.id in user_interest_ids else ""
            status_label = STATUS_LABELS.get(evt.status.value, evt.status.value)
            line = (
                f"• *{evt.name}*\n"
                f"  {evt.date.strftime('%d %B %Y')} · {evt.time.strftime('%H:%M')} · {loc}\n"
                f"  {evt.description}\n"
                f"  <@{evt.creator_slack_id}>  · {count} ilgili{interested_marker}\n"
                f"  _{status_label}_"
            )
            builder.add_text(line)
        builder.add_divider()
        builder.add_context([f"Toplam: {len(items)} etkinlik"])

    client.chat_postEphemeral(channel=channel_id, user=user_id, text="Geçmiş Etkinlikler", blocks=builder.build())


# ---------------------------------------------------------------------------
# /event add_me — Modal ile secim
# ---------------------------------------------------------------------------

INTEREST_FORM_DAYS_AHEAD = 30


def _handle_add_me(client, body: dict, user_id: str, channel_id: str) -> None:
    """Ilgi gosterme modal'ini acar. Dropdown'da onumuzdeki 1 ay icinde
    kullanicinin henuz ilgi gostermedigi APPROVED etkinlikler listelenir.
    """
    async def _fetch_events():
        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            return await repo.list_approved_for_interest_form(user_id, INTEREST_FORM_DAYS_AHEAD)

    try:
        events = _run_async(_fetch_events())
    except Exception as e:
        _logger.error("[CMD] add_me fetch failed: %s", e)
        client.chat_postEphemeral(channel=channel_id, user=user_id,
                                   text="Etkinlikler yüklenemedi, tekrar deneyin.")
        return

    if not events:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text=(
                "Önümüzdeki 1 ay içinde ilgi gösterebileceğiniz etkinlik yok.\n"
                "Tüm etkinlikleri görmek için `/event list` komutunu kullanın."
            ),
        )
        return

    # Kullanici adlarini Slack API'den cek (cache)
    _name_cache: dict[str, str] = {}
    def _resolve_name(slack_id: str) -> str:
        if slack_id in _name_cache:
            return _name_cache[slack_id]
        try:
            resp = slack_client.bot_client.users_info(user=slack_id)
            if resp.get("ok"):
                profile = resp["user"].get("profile", {})
                name = profile.get("display_name") or profile.get("real_name") or resp["user"].get("real_name", slack_id)
                _name_cache[slack_id] = name
                return name
        except Exception:
            pass
        _name_cache[slack_id] = slack_id
        return slack_id

    # Dropdown secenekleri olustur — tarihe gore sirali
    options = []
    for evt in sorted(events, key=lambda e: (e.date, e.time)):
        creator_name = _resolve_name(evt.creator_slack_id)
        label = f"{evt.date.strftime('%d %b')} — {evt.name} ({creator_name})"
        if len(label) > 75:
            label = label[:72] + "..."
        options.append({
            "text": {"type": "plain_text", "text": label},
            "value": evt.id,
        })

    import json as _json
    client.views_open(
        trigger_id=body.get("trigger_id"),
        view={
            "type": "modal",
            "callback_id": "event_add_me_modal",
            "private_metadata": _json.dumps({"channel_id": channel_id}),
            "title": {"type": "plain_text", "text": "Etkinliğe İlgi Göster"},
            "submit": {"type": "plain_text", "text": "İlgi Göster"},
            "close": {"type": "plain_text", "text": "İptal"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "add_me_event_select",
                    "element": {
                        "type": "static_select",
                        "action_id": "val",
                        "placeholder": {"type": "plain_text", "text": "Etkinlik seçin..."},
                        "options": options,
                    },
                    "label": {"type": "plain_text", "text": "İlgi Gösterilecek Etkinlik"},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "_Önümüzdeki 1 ay içinde gerçekleşecek ve henüz ilgi göstermediğiniz etkinlikler._",
                        }
                    ],
                },
            ],
        },
    )


# ---------------------------------------------------------------------------
# /event cancel <id>
# ---------------------------------------------------------------------------

def _handle_cancel(client, body: dict, user_id: str, channel_id: str) -> None:
    """Iptal modal'ini acar. Dropdown'da kullanicinin yetkisine gore aktif etkinlikler listelenir."""
    is_admin = user_id in settings.slack_admins

    async def _fetch_events():
        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            if is_admin:
                return await repo.list_by_status(EventStatus.APPROVED)
            else:
                return await repo.list_by_creator_and_status(user_id, EventStatus.APPROVED)

    try:
        events = _run_async(_fetch_events())
    except Exception as e:
        _logger.error("[CMD] cancel fetch failed: %s", e)
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="Etkinlikler yüklenemedi.")
        return

    if not events:
        client.chat_postEphemeral(channel=channel_id, user=user_id,
                                   text="İptal edilebilecek aktif etkinliğiniz yok.")
        return

    # Kullanici adlarini Slack API'den cek (cache)
    _name_cache: dict[str, str] = {}
    def _resolve_name(slack_id: str) -> str:
        if slack_id in _name_cache:
            return _name_cache[slack_id]
        try:
            resp = slack_client.bot_client.users_info(user=slack_id)
            if resp.get("ok"):
                profile = resp["user"].get("profile", {})
                name = profile.get("display_name") or profile.get("real_name") or resp["user"].get("real_name", slack_id)
                _name_cache[slack_id] = name
                return name
        except Exception:
            pass
        _name_cache[slack_id] = slack_id
        return slack_id

    # Dropdown secenekleri olustur — tarihe gore sirali
    options = []
    for evt in sorted(events, key=lambda e: (e.date, e.time)):
        creator_name = _resolve_name(evt.creator_slack_id)
        label = f"{evt.date.strftime('%d %b')} — {evt.name} ({creator_name})"
        # Slack option text max 75 karakter
        if len(label) > 75:
            label = label[:72] + "..."
        options.append({
            "text": {"type": "plain_text", "text": label},
            "value": evt.id,
        })

    client.views_open(
        trigger_id=body.get("trigger_id"),
        view={
            "type": "modal",
            "callback_id": "event_cancel_modal",
            "title": {"type": "plain_text", "text": "Etkinlik İptal Et"},
            "submit": {"type": "plain_text", "text": "Etkinliği İptal Et"},
            "close": {"type": "plain_text", "text": "İptal"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "cancel_event_select",
                    "element": {
                        "type": "static_select",
                        "action_id": "val",
                        "placeholder": {"type": "plain_text", "text": "Etkinlik seçin..."},
                        "options": options,
                    },
                    "label": {"type": "plain_text", "text": "İptal Edilecek Etkinlik"},
                },
            ],
        },
    )


# ---------------------------------------------------------------------------
# /event update — 1. adim: etkinlik secim modal'i
# ---------------------------------------------------------------------------

def _handle_update(client, body: dict, user_id: str, channel_id: str) -> None:
    """Guncelleme icin etkinlik secim modal'ini acar (1. adim)."""
    is_admin = user_id in settings.slack_admins

    async def _fetch_events():
        async with db.session(read_only=True) as session:
            repo = EventRepository(session)
            if is_admin:
                return await repo.list_by_status(EventStatus.APPROVED)
            else:
                return await repo.list_by_creator_and_status(user_id, EventStatus.APPROVED)

    try:
        events = _run_async(_fetch_events())
    except Exception as e:
        _logger.error("[CMD] update fetch failed: %s", e)
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="Etkinlikler yüklenemedi.")
        return

    if not events:
        client.chat_postEphemeral(channel=channel_id, user=user_id,
                                   text="Güncellenebilecek aktif etkinliğiniz yok.")
        return

    # Kullanici adlarini Slack API'den cek (cache)
    _name_cache: dict[str, str] = {}
    def _resolve_name(slack_id: str) -> str:
        if slack_id in _name_cache:
            return _name_cache[slack_id]
        try:
            resp = slack_client.bot_client.users_info(user=slack_id)
            if resp.get("ok"):
                profile = resp["user"].get("profile", {})
                name = profile.get("display_name") or profile.get("real_name") or resp["user"].get("real_name", slack_id)
                _name_cache[slack_id] = name
                return name
        except Exception:
            pass
        _name_cache[slack_id] = slack_id
        return slack_id

    # Dropdown secenekleri olustur — tarihe gore sirali
    options = []
    for evt in sorted(events, key=lambda e: (e.date, e.time)):
        creator_name = _resolve_name(evt.creator_slack_id)
        label = f"{evt.date.strftime('%d %b')} — {evt.name} ({creator_name})"
        if len(label) > 75:
            label = label[:72] + "..."
        options.append({
            "text": {"type": "plain_text", "text": label},
            "value": evt.id,
        })

    client.views_open(
        trigger_id=body.get("trigger_id"),
        view={
            "type": "modal",
            "callback_id": "event_update_select_modal",
            "title": {"type": "plain_text", "text": "Etkinlik Güncelle"},
            "submit": {"type": "plain_text", "text": "Devam"},
            "close": {"type": "plain_text", "text": "İptal"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "update_event_select",
                    "element": {
                        "type": "static_select",
                        "action_id": "val",
                        "placeholder": {"type": "plain_text", "text": "Etkinlik seçin..."},
                        "options": options,
                    },
                    "label": {"type": "plain_text", "text": "Güncellenecek Etkinlik"},
                },
            ],
        },
    )


# ---------------------------------------------------------------------------
# /event help
# ---------------------------------------------------------------------------

def _handle_help(client, user_id: str, channel_id: str) -> None:
    builder = MessageBuilder()
    builder.add_header("Event Komutları")
    builder.add_text(
        "*`/event create`*\n"
        "Yeni etkinlik talebi oluştur. Form açılır, admin onayından sonra duyuru yapılır.\n\n"
        "*`/event list`*\n"
        "Bu ayın yaklaşan etkinliklerini listele.\n\n"
        "*`/event my_list`*\n"
        "Kendi oluşturduğum etkinlikleri listele.\n\n"
        "*`/event history`*\n"
        "Geçmiş etkinlikleri görüntüle.\n\n"
        "*`/event add_me`*\n"
        "İlgi formu açar. Önümüzdeki 1 ay içinde gerçekleşecek ve henüz ilgi göstermediğiniz "
        "etkinlikler listelenir. Her etkinliğe 1 kez ilgi gösterilebilir.\n\n"
        "*`/event update`*\n"
        "Güncelleme formu açar. Etkinlik sahibi kendi etkinliklerini görüp güncelleyebilir.\n\n"
        "*`/event cancel`*\n"
        "İptal formu açar. Etkinlik sahibi kendi etkinliklerini görüp iptal edebilir.\n\n"
        "*`/event help`*\n"
        "Bu yardım mesajını göster."
    )
    builder.add_divider()
    builder.add_context(["_Etkinlik ID'sini `/event list` ile öğrenebilirsin_"])

    client.chat_postEphemeral(channel=channel_id, user=user_id, text="Event Komutları", blocks=builder.build())
