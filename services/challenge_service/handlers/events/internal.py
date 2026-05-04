"""
Internal Challenge Events
Teslimat modalını açma butonu ve form gönderme işlemleri burada işlenir.
"""
from __future__ import annotations

from datetime import datetime, timezone

from slack_bolt import Ack, App
from sqlalchemy import select

from packages.database.manager import db
from packages.database.models.challenge import Challenge, ChallengeJuryMember, ChallengeStatus
from packages.settings import get_settings
from packages.slack.blocks.builder import MessageBuilder
from packages.slack.client import slack_client
from ...api.state import active_state
from ...core.event_loop import run_async
from ...logger import _logger
from ...manager import service_manager
from ...utils.slack_helpers import slack_helper
from ...utils.slack_user_sync import get_or_create

app: App = slack_client.app


@app.action("open_submission_modal")
def handle_open_submission_modal(ack: Ack, body: dict, client, action):
    """'Form ile Teslim Et' butonuna basıldığında modal açılır."""
    ack()
    
    challenge_id = action.get("value")
    trigger_id = body.get("trigger_id")
    user_id = body["user"]["id"]

    if not challenge_id:
        return

    # Teslimat süresi dolmuş mu?
    if not active_state.is_submission_open(challenge_id):
        slack_helper.post_ephemeral_or_dm(
            channel_id=body["channel"]["id"],
            user_id=user_id,
            text="⏳ Teslimat süreniz (10 dakika) maalesef doldu!",
        )
        return

    # Form blokları (GitHub Lin, Açıklama vs.)
    blocks = [
        {
            "type": "input",
            "block_id": "github_repo",
            "element": {
                "type": "plain_text_input",
                "action_id": "val",
                "placeholder": {"type": "plain_text", "text": "Örn: https://github.com/username/project"},
            },
            "label": {"type": "plain_text", "text": "GitHub Repository URL"},
        },
        {
            "type": "input",
            "block_id": "project_desc",
            "element": {
                "type": "plain_text_input",
                "action_id": "val",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "Proje ve çözümünüzü kısaca anlatın..."},
            },
            "label": {"type": "plain_text", "text": "Proje Açıklaması"},
        }
    ]

    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "team_submission_view",
            "private_metadata": challenge_id,
            "title": {"type": "plain_text", "text": "Projeyi Teslim Et"},
            "submit": {"type": "plain_text", "text": "Gönder"},
            "blocks": blocks,
        }
    )

    # İlk butona basan kişiyi meta'ya kaydet (sonrakiler üzerine yazılmaz)
    async def _track_modal_open():
        async with db.session() as session:
            challenge = await session.get(Challenge, challenge_id)
            if challenge and not (challenge.meta or {}).get("submission_modal_opened_by"):
                meta = dict(challenge.meta or {})
                meta["submission_modal_opened_by"] = {
                    "slack_id": user_id,
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                }
                challenge.meta = meta
                await session.commit()

    run_async(_track_modal_open())
    _logger.info("[EVT] Submission modal opened for challenge=%s by user=%s", challenge_id, user_id)


@app.view("team_submission_view")
def handle_team_submission_view(ack: Ack, body: dict, client, view):
    """Takım projesini modal ile gönderildiğinde çalışır."""
    challenge_id = view.get("private_metadata")
    if not challenge_id:
        ack()
        return

    # Teslimat süresi form doldurulurken bitmişse işlemi engelle (ack'ten önce)
    if not active_state.is_submission_open(challenge_id):
        ack(response_action="errors", errors={"github_repo": "⏳ Teslimat süresi (10 dakika) doldu, gönderim kabul edilemiyor."})
        return

    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]

    github_url = values.get("github_repo", {}).get("val", {}).get("value", "")
    description = values.get("project_desc", {}).get("val", {}).get("value", "")

    async def _process_submission():
        async with db.session() as session:
            # SELECT FOR UPDATE: eş zamanlı gönderim durumunda satırı kilitle.
            # İkinci istek ilk commit edilene kadar bekler; commit sonrası
            # status=COMPLETED görür ve reddedilir.
            stmt = (
                select(Challenge)
                .where(Challenge.id == challenge_id)
                .with_for_update()
            )
            result = await session.execute(stmt)
            challenge = result.scalars().first()

            if not challenge or challenge.status != ChallengeStatus.STARTED:
                return False

            challenge.status = ChallengeStatus.COMPLETED
            challenge.meta = dict(challenge.meta or {})
            challenge.meta["submission"] = {
                "submitted_by": user_id,
                "github_url": github_url,
                "description": description,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }
            await session.commit()
            return challenge

    updated = run_async(_process_submission())
    # Deadline'ı temizle — başarılı ya da başarısız, pencere artık kapalı
    active_state.clear_submission_deadline(challenge_id)

    if not updated:
        _logger.info("[EVT] Duplicate submission rejected: challenge=%s user=%s", challenge_id, user_id)
        # Modal gönderimi sırasında body'de channel yok; challenge kanalına ephemeral gönder
        try:
            record = service_manager.registry.get_challenge_by_challenge_id(challenge_id)
            if record:
                slack_helper.post_ephemeral_or_dm(
                    channel_id=record.channel_id,
                    user_id=user_id,
                    text="⚠️ Proje zaten teslim edildi — başka bir ekip üyesi sizi geçti!",
                )
        except Exception:
            pass
        return

    _logger.info("[EVT] Challenge %s SUBMITTED by %s", challenge_id, user_id)

    # 1. Eval kanalı aç (ekip + admin davet, challenge kanalı arşivle)
    eval_channel_id = run_async(
        _open_eval_channel(
            challenge_id=str(updated.id),
            challenge_channel_id=updated.challenge_channel_id,
        )
    )
    if not eval_channel_id:
        _logger.error("[EVT] Could not open eval channel for challenge=%s", updated.id)
        return

    # 2. Jüri ata (eval kanalı zaten açık)
    assigned = run_async(
        _assign_jury_to_challenge(
            challenge_id=str(updated.id),
            challenge_channel_id=updated.challenge_channel_id,
            eval_channel_id=eval_channel_id,
            submission_info={"github_url": github_url, "description": description},
        )
    )
    if not assigned:
        _logger.warning("[EVT] Jury assignment deferred for challenge=%s", updated.id)


async def _open_eval_channel(
    challenge_id: str,
    challenge_channel_id: str,
) -> str | None:
    """
    Submission sonrası değerlendirme kanalını hazırlar:
      1. Eval kanalı oluşturur.
      2. Admin + ekip üyelerini davet eder.
      3. Challenge kanalına son mesajı gönderir ve kanalı arşivler.
      4. DB'de evaluation_channel_id'yi kaydeder.
    Registry geçişi yapılmaz — jüri atanınca _assign_jury_to_challenge yapar.
    Returns eval_channel_id on success, None on failure.
    """
    # Ekip üyelerini registry'den al (jüri hariç tutmak için de lazım)
    record = service_manager.registry.get_challenge(challenge_channel_id)
    team_members = list(record.members) if record else []

    # Eval kanalı oluştur
    eval_channel_name = f"eval-{challenge_id[:8].lower()}"
    eval_channel_id = slack_helper.create_private_channel(eval_channel_name)
    if not eval_channel_id:
        _logger.error("[EVT] Could not create eval channel for challenge=%s", challenge_id)
        return None

    # Ekip üyelerini eval kanalına davet et.
    # Admin/owner/bot zaten create_private_channel tarafından bootstrap ediliyor;
    # tekrar göndermek Slack API'den "already_in_channel" hatası alır ve
    # toplu daveti tamamen iptal eder.
    if team_members:
        slack_helper.invite_users_to_channel(eval_channel_id, team_members)

    # Challenge kanalına son mesajı gönder ve arşivle
    try:
        slack_helper.user_client.chat_postMessage(
            channel=challenge_channel_id,
            text="✅ *Projeniz başarıyla teslim alındı!* Değerlendirme kanalı oluşturuldu — jüri atanıyor. Bu kanal arşivleniyor; sonuçları değerlendirme kanalında göreceksiniz. 🏆",
        )
    except Exception as e:
        _logger.warning("[EVT] Could not notify challenge channel %s: %s", challenge_channel_id, e)
    try:
        slack_helper.archive_channel(challenge_channel_id)
    except Exception as e:
        _logger.warning("[EVT] Could not archive challenge channel %s: %s", challenge_channel_id, e)

    # DB: evaluation_channel_id kaydet
    async def _save_eval_channel():
        async with db.session() as session:
            challenge = await session.get(Challenge, challenge_id)
            if not challenge:
                return False
            challenge.evaluation_channel_id = eval_channel_id
            await session.commit()
            return True

    saved = await _save_eval_channel()
    if not saved:
        _logger.error("[EVT] DB update failed for eval channel, challenge=%s", challenge_id)
        try:
            slack_helper.archive_channel(eval_channel_id)
        except Exception:
            pass
        return None

    _logger.info("[EVT] Eval channel opened: %s for challenge=%s", eval_channel_id, challenge_id)
    return eval_channel_id


async def _assign_jury_to_challenge(
    challenge_id: str,
    challenge_channel_id: str,
    eval_channel_id: str,
    submission_info: dict,
    *,
    notify_if_insufficient: bool = True,
) -> bool:
    """
    COMPLETED + eval kanalı açık bir challenge'a jüri kuyruğundan jüri atar.
    - Jüri üyelerini eval kanalına davet eder.
    - DB'ye ChallengeJuryMember kayıtlarını ekler.
    - Registry'yi challenge → evaluation olarak geçirir.
    Returns True if assignment succeeded, False if deferred (not enough jury).
    """
    settings = get_settings()
    needed = settings.evaluation_jury_count

    record = service_manager.registry.get_challenge(challenge_channel_id)
    exclude_ids = set(record.members) if record else set()

    available = service_manager.jury_queue.count_excluding(exclude_ids)
    if available < needed:
        _logger.warning(
            "[EVT] Not enough jury for challenge=%s (need=%d, available=%d)",
            challenge_id, needed, available,
        )
        if notify_if_insufficient:
            try:
                builder = MessageBuilder()
                builder.add_header("⚖️ Jüri Üyesi Aranıyor!")
                builder.add_text(
                    f"Bir proje değerlendirme için sıraya girdi! 🗳️\n"
                    f"Değerlendirme paneli için *{needed} jüri üyesine* ihtiyacımız var, "
                    f"şu an *{available}/{needed}* gönüllü mevcut.\n\n"
                    f"Katılmak için: `/jury join`"
                )
                builder.add_context(["Jüri üyeliği challenge katılımcılarına kapalıdır."])
                slack_helper.bot_client.chat_postMessage(
                    channel=settings.slack_challenge_channel,
                    text="⚖️ Jüri değerlendirmesi için gönüllü aranıyor!",
                    blocks=builder.build(),
                )
            except Exception as e:
                _logger.warning("[EVT] Could not post jury recruitment message: %s", e)
        return False

    jury_items = service_manager.jury_queue.pop_n_excluding(needed, exclude_ids)
    jury_slack_ids = [item.slack_id for item in jury_items]

    # Jürileri eval kanalına davet et
    slack_helper.invite_users_to_channel(eval_channel_id, jury_slack_ids)

    # DB: ChallengeJuryMember kayıtları oluştur + challenge_type snapshot
    async def _save():
        async with db.session() as session:
            from sqlalchemy.orm import joinedload
            # with_for_update(of=Challenge) locks only the challenges table row;
            # plain with_for_update() fails on LEFT OUTER JOIN (challenge_type nullable)
            stmt = (
                select(Challenge)
                .where(Challenge.id == challenge_id)
                .options(joinedload(Challenge.challenge_type))
                .with_for_update(of=Challenge)
            )
            result = await session.execute(stmt)
            challenge = result.unique().scalars().first()

            if not challenge or challenge.status != ChallengeStatus.COMPLETED:
                return None, None

            challenge.status = ChallengeStatus.IN_EVALUATION
            challenge.evaluation_started_at = datetime.now(timezone.utc)

            for slack_id in jury_slack_ids:
                user = await get_or_create(slack_id)
                jm = ChallengeJuryMember(
                    challenge_id=challenge.id,
                    user_id=str(user.id) if user else None,
                    slack_id=slack_id,
                )
                session.add(jm)

            ct = challenge.challenge_type
            challenge_type_snapshot = {
                "name": ct.name if ct else None,
                "description": ct.description if ct else None,
                "deadline_hours": ct.deadline_hours if ct else None,
                "checklist": list(ct.checklist or []) if ct else [],
                "category": ct.category.value.replace("_", " ").title() if ct else None,
            } if ct else None

            await session.commit()
            return challenge, challenge_type_snapshot

    challenge_record, challenge_type_snapshot = await _save()
    if not challenge_record:
        _logger.error("[EVT] DB save failed for jury assignment challenge=%s, re-enqueuing", challenge_id)
        for item in jury_items:
            service_manager.jury_queue.add(item)
        return False

    # Registry: challenge → evaluation geçişi
    service_manager.registry.transition_challenge_to_evaluation(
        challenge_id=challenge_id,
        evaluation_channel_id=eval_channel_id,
        jury=jury_slack_ids,
    )

    # Evaluation kanalına bildirim — proje detayları + checklist
    jury_mentions = " ".join(f"<@{uid}>" for uid in jury_slack_ids)
    github_url = submission_info.get("github_url", "")
    sub_description = submission_info.get("description", "")
    try:
        eval_builder = MessageBuilder()
        eval_builder.add_header("⚖️ Değerlendirme Paneli")
        eval_builder.add_text(f"*👨‍⚖️ Jüri Ekibi:* {jury_mentions}")

        if challenge_type_snapshot:
            ct = challenge_type_snapshot
            eval_builder.add_divider()
            project_lines = [
                f"*📌 Proje:* {ct['name']}",
                f"*🏷 Kategori:* {ct['category'] or '—'}",
            ]
            if ct["description"]:
                project_lines.append(f"*📝 Proje Tanımı:* {ct['description']}")
            if ct["deadline_hours"]:
                project_lines.append(f"*⏱ Süre:* {ct['deadline_hours']} saat")
            eval_builder.add_text("\n".join(project_lines))

            checklist = ct["checklist"]
            if checklist:
                checklist_text = "*📋 Kabul Kriterleri:*\n" + "\n".join(f"• {item}" for item in checklist)
                eval_builder.add_text(checklist_text)

        if github_url or sub_description:
            eval_builder.add_divider()
            submission_lines = ["*📦 Takım Teslimi*"]
            if github_url:
                submission_lines.append(f"*🔗 GitHub:* <{github_url}>")
            if sub_description:
                submission_lines.append(f"*💬 Teslim Notu:* {sub_description}")
            eval_builder.add_text("\n".join(submission_lines))

        eval_builder.add_divider()
        eval_builder.add_text(
            "*Değerlendirmeye başlamak için `/challenge evaluate` komutunu kullanın.*\n"
            "Her jüri üyesi bağımsız puanlama yapar; tüm jüriler tamamlayınca ortalama hesaplanır."
        )
        slack_helper.user_client.chat_postMessage(
            channel=eval_channel_id,
            text=f"⚖️ Değerlendirme Paneli | Jüri: {jury_mentions}",
            blocks=eval_builder.build(),
        )
    except Exception as e:
        _logger.warning("[EVT] Could not notify eval channel %s: %s", eval_channel_id, e)

    _logger.info("[EVT] Jury assigned to challenge=%s: %s", challenge_id, jury_slack_ids)
    return True
async def _try_assign_waiting_challenges() -> None:
    """
    Eval kanalı açılmış (evaluation_channel_id IS NOT NULL) ama jüri henüz
    atanmamış (COMPLETED) challenge'lara jüri atamayı dener.
    Yeni bir jüri kuyruğa katıldığında çağrılır.
    """
    async with db.session(read_only=True) as session:
        stmt = select(Challenge).where(
            Challenge.status == ChallengeStatus.COMPLETED,
            Challenge.evaluation_channel_id.is_not(None),
        )
        result = await session.execute(stmt)
        waiting = result.scalars().all()

    for challenge in waiting:
        if challenge.challenge_channel_id and challenge.evaluation_channel_id:
            submission_info = (challenge.meta or {}).get("submission", {})
            await _assign_jury_to_challenge(
                challenge_id=str(challenge.id),
                challenge_channel_id=challenge.challenge_channel_id,
                eval_channel_id=challenge.evaluation_channel_id,
                submission_info=submission_info,
                notify_if_insufficient=False,
            )


@app.action("surrender_challenge")
def handle_surrender_challenge(ack: Ack, body: dict, client, action):
    """'Projeyi Bırak' butonunu işler → Challenge NOT_COMPLETED, kanal arşivlenir."""
    ack()

    user_id = body["user"]["id"]
    challenge_id = action.get("value")
    if not challenge_id:
        return

    async def _surrender():
        async with db.session() as session:
            challenge = await session.get(Challenge, challenge_id)
            if not challenge or challenge.status != ChallengeStatus.STARTED:
                return None
            now = datetime.now(timezone.utc)
            challenge.status = ChallengeStatus.NOT_COMPLETED
            challenge.challenge_ended_at = now
            meta = dict(challenge.meta or {})
            meta["surrender"] = {
                "surrendered_by": user_id,
                "surrendered_at": now.isoformat(),
            }
            challenge.meta = meta
            await session.commit()
            return challenge

    surrendered = run_async(_surrender())
    active_state.clear_submission_deadline(challenge_id)

    if not surrendered:
        ch = body.get("channel", {}).get("id") or ""
        if ch:
            slack_helper.post_ephemeral_or_dm(
                channel_id=ch,
                user_id=user_id,
                text="❌ Challenge bırakılamadı — aktif bir challenge bulunamadı.",
            )
        return

    _logger.info("[EVT] Challenge %s surrendered by %s", challenge_id, user_id)

    if surrendered.challenge_channel_id:
        service_manager.registry.unregister_challenge(surrendered.challenge_channel_id)
        try:
            slack_helper.send_announcement(
                channel_id=surrendered.challenge_channel_id,
                text=f"🏳️ <@{user_id}> challenge'ı bıraktı. Kanal kapatılıyor..."
            )
            slack_helper.archive_channel(surrendered.challenge_channel_id)
        except Exception as e:
            _logger.warning("[EVT] Could not archive channel %s after surrender: %s", surrendered.challenge_channel_id, e)


