"""
Evaluation Event Handlers
Jürinin gönderdiği puanlama (submission) olaylarını yönetir.
"""
from __future__ import annotations

from datetime import datetime, timezone

from slack_bolt import Ack, App
from sqlalchemy import select

from packages.database.manager import db
from packages.database.models.challenge import Challenge, ChallengeStatus
from packages.settings import get_settings
from packages.slack.client import slack_client
from ...core.event_loop import run_async
from ...logger import _logger
from ...manager import service_manager
from ...utils.notifications import notify_challenge_eval_completed_admin
from ...utils.slack_helpers import slack_helper

app: App = slack_client.app


@app.view("jury_evaluation_view")
def handle_jury_evaluation_submission(ack: Ack, body: dict, view):
    """Jürinin değerlendirme formunu göndermesi anında çalışır."""
    ack()

    user_id = body["user"]["id"]
    challenge_id = view.get("private_metadata")
    if not challenge_id:
        return

    # Verileri al
    values = view["state"]["values"]
    
    # Tüm cevapları topla ve genel ortalama (puan) hesapla
    total_score = 0.0
    answered_count = 0
    raw_answers = {}

    for block_id, block_data in values.items():
        if block_id.startswith("crit_"):
            crit_id = block_id.split("_", 1)[1]
            # Val isimli static_select'ten geleni oku
            val = block_data.get("val", {}).get("selected_option", {}).get("value")
            
            raw_answers[crit_id] = val
            
            # Puanlamaya kat
            if val == "true":
                total_score += 10.0  # boolean 'evet' 10 puan gibi varsayalım
                answered_count += 1
            elif val == "false":
                total_score += 0.0
                answered_count += 1
            elif val and val.isdigit():
                total_score += float(val)
                answered_count += 1

    final_score = (total_score / answered_count) if answered_count > 0 else 0.0

    async def _save_evaluation():
        async with db.session() as session:
            from sqlalchemy.orm import joinedload, selectinload
            # SELECT FOR UPDATE: aynı jüri üyesinin eş zamanlı çift gönderimini engeller.
            stmt = (
                select(Challenge)
                .where(Challenge.id == challenge_id)
                .options(
                    joinedload(Challenge.challenge_jury_members),
                    selectinload(Challenge.challenge_team_members),
                    joinedload(Challenge.challenge_type),
                )
                .with_for_update(of=Challenge)
            )
            result = await session.execute(stmt)
            challenge = result.unique().scalars().first()

            if not challenge or challenge.status not in (ChallengeStatus.COMPLETED, ChallengeStatus.IN_EVALUATION):
                return False, False, 0.0, None

            # İlgili ChallengeJuryMember'ı bul
            jury_member = next((jm for jm in challenge.challenge_jury_members if jm.slack_id == user_id), None)
            if not jury_member:
                return False, False, 0.0, None

            # Bu jüri üyesi zaten değerlendirdi mi? (FOR UPDATE sonrası taze veriyle kontrol)
            if (jury_member.meta or {}).get("evaluation"):
                return False, False, 0.0, None

            # Jüri'nin meta bilgisine değerlendirmeyi ekle
            meta = dict(jury_member.meta or {})
            meta["evaluation"] = {
                "score": final_score,
                "raw_answers": raw_answers,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
            jury_member.meta = meta

            now = datetime.now(timezone.utc)

            # Tüm jüriler değerlendirdi mi? (güncellenen üye dahil)
            evaluated_count = sum(
                1 for jm in challenge.challenge_jury_members
                if (jm.meta or {}).get("evaluation")
            )
            total_jury = len(challenge.challenge_jury_members)
            is_last_jury = evaluated_count == total_jury
            average_score = 0.0
            announcement = None

            if is_last_jury and evaluated_count > 0:
                average_score = sum(
                    jm.meta["evaluation"]["score"]
                    for jm in challenge.challenge_jury_members
                    if (jm.meta or {}).get("evaluation")
                ) / evaluated_count

                challenge.status = ChallengeStatus.EVALUATED
                challenge.evaluation_score = average_score
                challenge.challenge_ended_at = now
                challenge.evaluation_ended_at = now

                # Commit öncesi snapshot al — commit sonrası attribute'lar expire olur
                submission = (challenge.meta or {}).get("submission", {})
                announcement = {
                    "challenge_id": str(challenge.id),
                    "challenge_type_id": challenge.challenge_type.id if challenge.challenge_type else None,
                    "challenge_type_name": challenge.challenge_type.name if challenge.challenge_type else None,
                    "team": [
                        tm.slack_id for tm in challenge.challenge_team_members
                        if tm.slack_id
                    ],
                    "jury": [
                        jm.slack_id for jm in challenge.challenge_jury_members
                        if jm.slack_id
                    ],
                    "project_name": challenge.challenge_type.name if challenge.challenge_type else None,
                    "github_url": submission.get("github_url", ""),
                    "description": submission.get("description", ""),
                    "score": average_score,
                    "evaluation_channel_id": challenge.evaluation_channel_id,
                    "challenge_channel_id": challenge.challenge_channel_id,
                }

            await session.commit()
            return challenge, is_last_jury, average_score, announcement

    challenge_record, is_last_jury, average_score, announcement = run_async(_save_evaluation())

    if challenge_record:
        if is_last_jury:
            _logger.info("[EVT] Challenge %s EVALUATED completely. Avg score: %.2f", challenge_id, average_score)
            eval_channel_id = challenge_record.evaluation_channel_id

            # Eval kanalına son mesaj (user_client — private kanal)
            try:
                slack_helper.user_client.chat_postMessage(
                    channel=eval_channel_id,
                    text=f"✅ Tüm jüri üyeleri puanlamayı tamamladı! Projenin nihai ortalama puanı: *{average_score:.1f}*. Meydan okuma resmen sona ermiştir 🏆."
                )
            except Exception as e:
                _logger.error("[EVT] Could not post final evaluation result: %s", e)

            # Ortak kanala başarı duyurusu (bot_client — genel kanal)
            if announcement:
                try:
                    notify_challenge_eval_completed_admin(
                        challenge_id=announcement["challenge_id"],
                        evaluation_channel_id=announcement.get("evaluation_channel_id"),
                        average_score=average_score,
                        challenge_type_id=announcement.get("challenge_type_id"),
                        challenge_type_name=announcement.get("challenge_type_name"),
                    )
                except Exception as e:
                    _logger.error("[EVT] Could not notify admin eval complete: %s", e)
                try:
                    _post_success_announcement(announcement)
                except Exception as e:
                    _logger.error("[EVT] Could not post success announcement: %s", e)

            # Registry'den temizle ve eval kanalını arşivle
            service_manager.registry.unregister_evaluation(eval_channel_id)
            try:
                slack_helper.archive_channel(eval_channel_id)
                _logger.info("[EVT] Eval channel %s archived after evaluation", eval_channel_id)
            except Exception as e:
                _logger.warning("[EVT] Could not archive eval channel %s: %s", eval_channel_id, e)
        else:
            _logger.info("[EVT] Jury %s evaluated challenge %s. Waiting for others...", user_id, challenge_id)
            try:
                slack_helper.user_client.chat_postEphemeral(
                    channel=challenge_record.evaluation_channel_id,
                    user=user_id,
                    text="✅ Değerlendirmeniz kaydedildi. Diğer jüri üyelerinin tamamlaması bekleniyor."
                )
            except Exception:
                pass
    else:
        _logger.warning("[EVT] Evaluation rejected: challenge=%s user=%s", challenge_id, user_id)
        # Modal gönderiminde body'de channel yok; eval kanalını registry'den bul
        try:
            eval_record = next(
                (r for r in service_manager.registry.evaluation_channels().values() if r.challenge_id == challenge_id),
                None,
            )
            if eval_record:
                slack_helper.user_client.chat_postEphemeral(
                    channel=eval_record.channel_id,
                    user=user_id,
                    text="❌ Değerlendirmeniz kaydedilemedi — zaten değerlendirmiş olabilirsiniz veya challenge uygun aşamada değil.",
                )
        except Exception:
            pass


def _post_success_announcement(ann: dict) -> None:
    """Başarıyla tamamlanan challenge'ı ortak kanala duyurur (bot_client — genel kanal)."""
    settings = get_settings()

    team_mentions = " ".join(f"<@{uid}>" for uid in ann["team"]) or "—"
    jury_mentions = " ".join(f"<@{uid}>" for uid in ann["jury"]) or "—"
    project_name = ann["project_name"] or "Bilinmiyor"
    github_url = ann["github_url"]
    description = ann["description"]
    score = ann["score"]

    lines = [
        "🏆 *Bir Challenge Başarıyla Tamamlandı!*",
        "",
        f"*📌 Proje:* {project_name}",
    ]
    if description:
        lines.append(f"*📝 Açıklama:* {description}")
    if github_url:
        lines.append(f"*🔗 GitHub:* <{github_url}>")
    lines += [
        "",
        f"*👥 Ekip:* {team_mentions}",
        f"*👨‍⚖️ Jüri:* {jury_mentions}",
        "",
        f"*⭐ Nihai Puan: {score:.1f}*",
    ]

    slack_helper.bot_client.chat_postMessage(
        channel=settings.slack_challenge_channel,
        text=f"🏆 Challenge tamamlandı! Puan: {score:.1f}",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}],
    )

