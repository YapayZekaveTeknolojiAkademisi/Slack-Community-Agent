"""
Challenge Event Handlers
Slack'teki etkileşimli olaylar (modal submission, actions) burada yönetilir.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from slack_bolt import Ack, App

from packages.database.manager import db
from packages.database.models.challenge import Challenge, ChallengeCategory, ChallengeStatus, ChallengeTeamMember
from packages.database.repository.challenge import ChallengeTypeRepository
from packages.slack.blocks.builder import BlockBuilder, MessageBuilder
from packages.slack.client import slack_client
from packages.settings import get_settings
from ...core.event_loop import run_async
from ...core.queue.channel_registry import ChannelRecord
from ...core.queue.challenge_queue import QueueItem
from ...manager import service_manager
from ...utils.notifications import notify_challenge_community_launch_long, notify_challenge_launched_admin
from ...utils.slack_helpers import slack_helper
from ...utils.slack_user_sync import get_or_create
from ...logger import _logger

app: App = slack_client.app
settings = get_settings()


# ---------------------------------------------------------------------------
# Senaryo 1: /challenge join → Kullanıcı kuyruğa girer
# ---------------------------------------------------------------------------

@app.view("challenge_join_modal")
def handle_join_modal_submission(ack: Ack, body: dict, client, view):
    """Kategori seçim modalinin gönderilmesini işler → Kuyruğa ekle."""
    user_id = body["user"]["id"]

    values = view["state"]["values"]
    selected = values["category_block"]["category_select"]["selected_option"]["value"]
    category = ChallengeCategory(selected)

    # Zaten kuyrukta veya pending'de mi?
    engaged, reason = service_manager.is_user_engaged(user_id)
    if engaged:
        ack(response_action="errors", errors={"category_block": f"Zaten {reason}!"})
        return

    ack()

    cat_label = category.value.replace("_", " ").title()

    # Önce bu kategori için bekleyen (pending) bir challenge var mı kontrol et
    pending_id_found = None
    pending_found = None
    already_in_pending = False
    with service_manager.pending_lock:
        for pid, p in list(service_manager.pending_challenges.items()):
            if user_id in p["participants"]:
                # Concurrent pop_n + join race: kullanıcı zaten pending'e alınmış
                already_in_pending = True
                break
            if p["category"] == category:
                p["participants"].append(user_id)
                pending_id_found = pid
                pending_found = p
                break

    if already_in_pending:
        client.chat_postEphemeral(
            channel=settings.slack_challenge_channel, user=user_id,
            text="⚡ Zaten bir bekleme listesine eklendiniz — challenge kanalına davet bekleniyor."
        )
        return

    if pending_id_found:
        current = len(pending_found["participants"])
        num = pending_found["num"]

        if current >= num:
            # Ekip doldu → başlat
            with service_manager.pending_lock:
                if pending_id_found not in service_manager.pending_challenges:
                    # Başka bir thread zaten başlattı; bu kullanıcı participants'a
                    # eklendi, challenge'a dahil oldu — bildir ve çık
                    client.chat_postEphemeral(
                        channel=settings.slack_challenge_channel, user=user_id,
                        text="⚡ Tam dolu oldu! Siz de ekibe dahil edildiniz — challenge kanalına davet bekleniyor."
                    )
                    return
                participants = list(pending_found["participants"])
                del service_manager.pending_challenges[pending_id_found]

            _logger.info("[EVT] Pending %s full via join modal, launching", pending_id_found)
            if pending_found.get("message_ts"):
                try:
                    client.chat_update(
                        channel=settings.slack_challenge_channel,
                        ts=pending_found["message_ts"],
                        text=f"✅ {cat_label} Challenge başladı! Ekip tamamlandı.",
                        blocks=[BlockBuilder.section(text=f"✅ *{cat_label} Challenge* başladı! Tüm yerler doldu.")]
                    )
                except Exception as e:
                    _logger.warning("[EVT] Could not update invite message on launch: %s", e)
            _launch_challenge(client, category, participants)
        else:
            # Henüz dolmadı → mesajı güncelle
            _post_join_invitation(client, pending_id_found, category, num, current_count=current)
            client.chat_postEphemeral(
                channel=settings.slack_challenge_channel,
                user=user_id,
                text=f"✅ *{cat_label}* challenge'ına katıldın! *{current}/{num}* kişi hazır, bekliyoruz..."
            )
    else:
        # Bekleyen challenge yok → kuyruğa ekle
        service_manager.category_queues[category].add(QueueItem(slack_id=user_id))
        _logger.info("[EVT] User %s joined %s queue", user_id, category.value)
        client.chat_postEphemeral(
            channel=settings.slack_challenge_channel,
            user=user_id,
            text=f"✅ <@{user_id}>, *{category.value.upper()}* kuyruğuna eklendin! Eşleşme olduğunda bilgilendirileceğiz."
        )


# ---------------------------------------------------------------------------
# Senaryo 2: /challenge start <n> → Kategori seç → Matchmaking
# ---------------------------------------------------------------------------

@app.view("challenge_start_modal")
def handle_start_modal_submission(ack: Ack, body: dict, client, view):
    """Start modalinin gönderilmesini işler → Matchmaking."""
    user_id = body["user"]["id"]

    # Modal açıldıktan sonra kullanıcı başka bir kuyruğa girmiş olabilir
    engaged, reason = service_manager.is_user_engaged(user_id)
    if engaged:
        ack(response_action="errors", errors={"category_block": f"Zaten {reason}!"})
        return

    ack()

    meta = json.loads(view.get("private_metadata") or "{}")
    num: int = int(meta.get("num", 2))

    values = view["state"]["values"]
    selected = values["category_block"]["category_select"]["selected_option"]["value"]
    category = ChallengeCategory(selected)

    queue = service_manager.category_queues[category]

    # Kuyruktan alabileceğimiz kadar al (en fazla n-1 kişi)
    take = min(queue.count(), num - 1)
    popped = queue.pop_n(take) if take > 0 else []
    participants = [user_id] + [item.slack_id for item in popped]

    _logger.info("[EVT] Start %s: initiator=%s, from_queue=%s, total=%s/%s",
                 category.value, user_id, len(popped), len(participants), num)

    if len(participants) >= num:
        # Ekip tamam → Direkt başlat, kanal açılır
        _launch_challenge(client, category, participants, popped_items=popped)
    else:
        # Eksik var → Kanal açılmaz, pending oluştur ve davet butonu at
        pending_id = str(uuid.uuid4())[:8]
        with service_manager.pending_lock:
            service_manager.pending_challenges[pending_id] = {
                "category": category,
                "num": num,
                "participants": participants,   # Başlatıcı + kuyruktan gelenler
                "message_ts": None,
                "created_at": datetime.now(timezone.utc),
            }
        _post_join_invitation(client, pending_id, category, num, current_count=len(participants))
        _logger.info("[EVT] Pending %s created: %s/%s", pending_id, len(participants), num)

        client.chat_postEphemeral(
            channel=settings.slack_challenge_channel,
            user=user_id,
            text=(
                f"⏳ *{category.value.upper()}* için {len(participants)}/{num} kişi hazır. "
                f"Kanala katılım daveti gönderildi — kanal {num} kişi dolunca açılacak."
            )
        )


def _post_join_invitation(client, pending_id: str, category: ChallengeCategory, num: int, current_count: int):
    """Challenge kanalına katılım daveti mesajı atar veya günceller."""
    cat_label = category.value.replace("_", " ").title()
    builder = MessageBuilder()
    builder.add_header(f"🚀 Aktif {cat_label} Challenge — Katılmak İster misin?")
    builder.add_text(
        f"*{current_count}/{num}* kişi hazır. Hâlâ *{num - current_count}* kişiye ihtiyaç var.\n\n"
        f"Katılmak için `/challenge join` komutunu yaz ve *{cat_label}* kategorisini seç."
    )
    builder.add_context([f"Kategori: *{cat_label}*  ·  Kod: `{pending_id}`"])

    pending = service_manager.pending_challenges.get(pending_id)
    if pending and pending.get("message_ts"):
        # Mevcut mesajı güncelle
        try:
            client.chat_update(
                channel=settings.slack_challenge_channel,
                ts=pending["message_ts"],
                text=f"🚀 Aktif {cat_label} Challenge — {current_count}/{num} kişi",
                blocks=builder.build()
            )
        except Exception as e:
            _logger.warning("[EVT] Could not update invite message: %s", e)
    else:
        # Yeni mesaj at
        try:
            resp = client.chat_postMessage(
                channel=settings.slack_challenge_channel,
                text=f"🚀 Aktif {cat_label} Challenge — {current_count}/{num} kişi",
                blocks=builder.build()
            )
            if pending:
                pending["message_ts"] = resp.get("ts")
        except Exception as e:
            _logger.error("[EVT] Could not post invite message: %s", e)



# ---------------------------------------------------------------------------
# Ortak: Challenge Başlatma (DB + Slack Kanal + Registry)
# ---------------------------------------------------------------------------

def _launch_challenge(client, category: ChallengeCategory, participants: list[str], popped_items: list | None = None):
    """
    Matchmaking tamamlandığında çağrılır:
    1. Slack kanalı oluştur ve ekibi davet et
    2. DB'ye Challenge kaydı oluştur
    3. ChannelRegistry'e kaydet
    4. Katılımcılara duyuru yap
    """
    cat_label = category.value.replace("_", " ").title()
    channel_name = f"challenge-{category.value.replace('_', '-')}-{uuid.uuid4().hex[:6]}"

    # 1. Slack kanalı oluştur
    channel_id = slack_helper.create_private_channel(channel_name)
    if not channel_id:
        _logger.error("[EVT] Could not create channel for %s", category.value)
        if popped_items:
            service_manager.re_enqueue(popped_items, category)
        return

    # 2. Katılımcıları davet et
    slack_helper.invite_users_to_channel(channel_id, participants)

    # 3. DB'ye kaydet (async → senkron köprü)
    async def _create_db_record():
        # Önce tüm katılımcıları DB'de eşle/oluştur
        user_map: dict[str, str | None] = {}
        for slack_id in participants:
            user = await get_or_create(slack_id)
            user_map[slack_id] = str(user.id) if user else None

        async with db.session() as session:
            # Katılımcıların daha önce yapmadığı rastgele bir proje tipi seç
            type_repo = ChallengeTypeRepository(session)
            challenge_type = await type_repo.pick_random_for_participants(
                category=category,
                participant_slack_ids=participants,
            )
            if not challenge_type:
                _logger.warning("[EVT] No ChallengeType found for category=%s", category.value)

            challenge = Challenge(
                challenge_type_id=challenge_type.id if challenge_type else None,
                creator_slack_id=participants[0],
                status=ChallengeStatus.STARTED,
                challenge_channel_id=channel_id,
                challenge_started_at=datetime.now(timezone.utc),
            )
            session.add(challenge)
            await session.flush()

            for slack_id in participants:
                member = ChallengeTeamMember(
                    challenge_id=challenge.id,
                    user_id=user_map.get(slack_id),
                    slack_id=slack_id,
                )
                session.add(member)
            await session.flush()
            _logger.info(
                "[EVT] Challenge %s created in DB: channel=%s type=%s",
                challenge.id, channel_id, challenge_type.id if challenge_type else "none",
            )
            return challenge.id, challenge_type

    try:
        challenge_id, challenge_type = run_async(_create_db_record())
    except Exception as e:
        _logger.error("[EVT] DB record failed for channel %s: %s", channel_id, e)
        challenge_id = "unknown"
        challenge_type = None

    # 4. ChannelRegistry'e kaydet
    service_manager.registry.register_challenge(
        ChannelRecord(
            channel_id=channel_id,
            challenge_id=challenge_id,
            members=participants,
            jury=[],
            admin_slack_id=settings.slack_admin_slack_id,
        )
    )

    # 5. Kanala karşılama mesajı + atanan proje tipi
    mentions = " ".join(f"<@{uid}>" for uid in participants)
    builder = MessageBuilder()
    builder.add_header(f"🎉 {cat_label} Challenge Başladı!")
    builder.add_text(f"*👥 Ekip:* {mentions}")

    if challenge_type:
        detail_lines = [
            f"*📌 Proje:* {challenge_type.name}",
            f"*🏷 Kategori:* {cat_label}",
        ]
        if challenge_type.description:
            detail_lines.append(f"*📝 Açıklama:* {challenge_type.description}")
        if challenge_type.deadline_hours:
            detail_lines.append(f"*⏱ Süre:* `{challenge_type.deadline_hours}` saat")
        detail_lines.append(f"*⭐ Şablon puanı:* `{challenge_type.points}`")
        builder.add_text("\n".join(detail_lines))

        checklist = challenge_type.checklist or []
        if checklist:
            builder.add_divider()
            checklist_text = "*📋 Kabul Kriterleri:*\n" + "\n".join(f"☐  {item}" for item in checklist)
            builder.add_text(checklist_text)
    else:
        builder.add_text("⚠️ Bu kategori için henüz proje tanımlanmamış — admin yakında atayacak.")

    builder.add_divider()
    builder.add_text(
        "*📦 Proje Teslimi*\n"
        "Projenizi tamamladığınızda `/challenge submit` komutunu yazın — 10 dakikalık teslim penceresi açılır.\n"
        "GitHub repo linkinizi ve kısa bir teslim notu hazır bulundurun."
    )
    builder.add_context(["Başarılar! 🚀  ·  Sorularınız için admin'e ulaşın."])

    slack_helper.send_announcement(
        channel_id=channel_id,
        text=f"🎉 {cat_label} Challenge Başladı! Ekip: {mentions}",
        blocks=builder.build(),
    )

    if challenge_id != "unknown":
        notify_challenge_launched_admin(
            challenge_id=challenge_id,
            challenge_channel_id=channel_id,
            category_label=cat_label,
            challenge_type_id=challenge_type.id if challenge_type else None,
            challenge_type_name=challenge_type.name if challenge_type else None,
            points=challenge_type.points if challenge_type else None,
            participant_slack_ids=participants,
        )

    notify_challenge_community_launch_long(
        challenge_id=challenge_id,
        challenge_channel_id=channel_id,
        category_label=cat_label,
        challenge_type_name=challenge_type.name if challenge_type else None,
        challenge_type_description=challenge_type.description if challenge_type else None,
        deadline_hours=challenge_type.deadline_hours if challenge_type else None,
        points=challenge_type.points if challenge_type else None,
        participant_slack_ids=participants,
    )

    _logger.info(
        "[EVT] Challenge launched: channel=%s category=%s type=%s participants=%s",
        channel_id, category.value,
        challenge_type.id if challenge_type else "none",
        participants,
    )
