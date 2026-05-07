from slack_bolt import Ack, App
from packages.slack.client import slack_client
from packages.settings import get_settings
from packages.database.manager import db
from packages.database.repository.challenge import ChallengeRepository
from packages.database.models.challenge import ChallengeCategory
from ...manager import service_manager
from ...core.event_loop import run_async
from packages.slack.blocks.builder import MessageBuilder, BlockBuilder
from ...logger import _logger
from .internal import handle_submit
from .evaluation import handle_evaluate

app: App = slack_client.app
settings = get_settings()


@app.command("/challenge")
def handle_challenge_command(ack: Ack, body: dict, client, command):
    ack()

    user_id = body.get("user_id")
    channel_id = body.get("channel_id", "")
    args = body.get("text", "").strip().split()
    cmd = args[0].lower() if args else "join"

    # Jury, submit ve evaluate özel kanallardan çalışır — kanal kontrolünden önce yönlendir
    if cmd == "jury":
        from .jury import handle_jury
        handle_jury(client, body, args[1:])
        return

    if cmd == "submit":
        handle_submit(client, body)
        return

    if cmd == "evaluate":
        handle_evaluate(client, body)
        return

    # Diğer komutlar sadece yetkili challenge kanalında çalışır
    if channel_id != settings.slack_challenge_channel:
        msg = f"⚠️ Bu komut sadece <#{settings.slack_challenge_channel}> kanalında kullanılabilir."
        # Bot üye olmadığı kanallarda ephemeral başarısız olur — her durumda DM gönder
        client.chat_postMessage(channel=user_id, text=msg)
        return

    # Kullanıcının kuyrukta veya pending'de olup olmadığını kontrol et
    engaged, engaged_reason = service_manager.is_user_engaged(user_id)

    # Leave yalnızca kuyruk/pending için geçerli; aktif kanal üyeliğinde önermek yanıltıcı
    can_leave = "kuyruğundasınız" in engaged_reason or "bekleme listesinde" in engaged_reason

    # 2. Komut Yönlendirme ve Kısıtlamalar
    if cmd == "join":
        if engaged:
            suffix = " Kuyruktan çıkmak için `/challenge leave` kullanın." if can_leave else ""
            client.chat_postEphemeral(
                channel=settings.slack_challenge_channel,
                user=user_id,
                text=f"❌ Zaten {engaged_reason}!{suffix}"
            )
        else:
            open_join_modal(client, body.get("trigger_id"), user_id)

    elif cmd == "start":
        if engaged:
            suffix = " Kuyruktan çıkmak için `/challenge leave` kullanın." if can_leave else ""
            client.chat_postEphemeral(
                channel=settings.slack_challenge_channel,
                user=user_id,
                text=f"❌ {engaged_reason}.{suffix}"
            )
        else:
            try:
                num = int(args[1]) if len(args) > 1 else 2
                open_start_modal(client, body.get("trigger_id"), user_id, num)
            except ValueError:
                client.chat_postEphemeral(
                    channel=settings.slack_challenge_channel,
                    user=user_id,
                    text="⚠️ Geçersiz sayı. Kullanım: `/challenge start <sayı>` (ör. `/challenge start 3`)"
                )

    elif cmd == "leave":
        if not engaged:
            client.chat_postEphemeral(
                channel=settings.slack_challenge_channel,
                user=user_id,
                text="🧐 Herhangi bir kuyrukta veya bekleme listesinde değilsiniz."
            )
        elif not can_leave:
            client.chat_postEphemeral(
                channel=settings.slack_challenge_channel,
                user=user_id,
                text=f"⚠️ {engaged_reason} olduğunuz için kuyruktan çıkamazsınız.\n"
                     "Projeyi bırakmak istiyorsanız challenge kanalınızdaki *Projeyi Bırak* butonunu kullanın."
            )
        else:
            handle_leave(client, user_id, settings.slack_challenge_channel)

    elif cmd == "list":
        handle_list(client, user_id, settings.slack_challenge_channel)

    elif cmd == "info":
        handle_info(client, user_id, settings.slack_challenge_channel)

    elif cmd == "help":
        handle_help(client, user_id, settings.slack_challenge_channel)

    else:
        client.chat_postEphemeral(
            channel=settings.slack_challenge_channel,
            user=user_id,
            text="❓ Bilinmeyen komut. Kullanılabilir komutları görmek için `/challenge help` yazın."
        )

def open_join_modal(client, trigger_id, user_id):
    """Kategori seçimi için modal açar."""
    options = [
        {"label": "📚 Learn (Öğrenme Odaklı)", "value": ChallengeCategory.LEARN.value},
        {"label": "🛠️ Practice (Pratik Yapma)", "value": ChallengeCategory.PRACTICE.value},
        {"label": "🌍 Real World (Gerçek Senaryo)", "value": ChallengeCategory.REAL_WORLD.value},
        {"label": "🚀 No-Code / Low-Code", "value": ChallengeCategory.NO_CODE_LOW_CODE.value},
    ]

    view = {
        "type": "modal",
        "callback_id": "challenge_join_modal",
        "title": {"type": "plain_text", "text": "Challenge'a Katıl"},
        "submit": {"type": "plain_text", "text": "Kuyruğa Gir"},
        "close": {"type": "plain_text", "text": "İptal"},
        "blocks": [
            BlockBuilder.section(
                text=f"Selam <@{user_id}>! Hangi kategoride bir meydan okuma arıyorsun?"
            ),
            {
                "type": "input",
                "block_id": "category_block",
                "element": {
                    "type": "static_select",
                    "action_id": "category_select",
                    "placeholder": {"type": "plain_text", "text": "Kategori seçin..."},
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": opt["label"], "emoji": True},
                            "value": opt["value"]
                        } for opt in options
                    ]
                },
                "label": {"type": "plain_text", "text": "Meydan Okuma Kategorisi"}
            }
        ]
    }
    client.views_open(trigger_id=trigger_id, view=view)


def open_start_modal(client, trigger_id: str, user_id: str, num: int):
    """Start için kategori seçim modalini açar. num private_metadata üzerinden taşınır."""
    import json
    options = [
        {"label": "📚 Learn (Öğrenme Odaklı)", "value": ChallengeCategory.LEARN.value},
        {"label": "🛠️ Practice (Pratik Yapma)", "value": ChallengeCategory.PRACTICE.value},
        {"label": "🌍 Real World (Gerçek Senaryo)", "value": ChallengeCategory.REAL_WORLD.value},
        {"label": "🚀 No-Code / Low-Code", "value": ChallengeCategory.NO_CODE_LOW_CODE.value},
    ]
    view = {
        "type": "modal",
        "callback_id": "challenge_start_modal",
        "private_metadata": json.dumps({"num": num}),
        "title": {"type": "plain_text", "text": f"Challenge Başlat"},
        "submit": {"type": "plain_text", "text": "Başlat"},
        "close": {"type": "plain_text", "text": "İptal"},
        "blocks": [
            BlockBuilder.section(
                text=f"<@{user_id}>, sen dahil *{num} kişilik* bir ekip için kategori seç. Kuyruktan {num - 1} kişi otomatik eklenecek."
            ),
            {
                "type": "input",
                "block_id": "category_block",
                "element": {
                    "type": "static_select",
                    "action_id": "category_select",
                    "placeholder": {"type": "plain_text", "text": "Kategori seçin..."},
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": opt["label"], "emoji": True},
                            "value": opt["value"]
                        } for opt in options
                    ]
                },
                "label": {"type": "plain_text", "text": "Challenge Kategorisi"}
            }
        ]
    }
    client.views_open(trigger_id=trigger_id, view=view)

def handle_help(client, user_id, channel_id):
    """Tüm challenge ve jury komutlarını ephemeral mesaj olarak listeler."""
    builder = MessageBuilder()
    builder.add_header("📖 Challenge Komutları")

    builder.add_text(
        "*`/challenge join`*\n"
        "Challenge kuyruğuna katıl. Kategori seçim ekranı açılır; eşleşme olduğunda challenge kanalına davet edilirsin.\n\n"
        "*`/challenge start <sayı>`*\n"
        "Belirtilen sayıda kişilik bir challenge başlat (varsayılan: 2). "
        "Kuyruktan katılımcı toplanır; yeterli kişi yoksa katılım daveti yayınlanır.\n\n"
        "*`/challenge leave`*\n"
        "Kuyruktan veya bekleme listesinden çık.\n"
        "• Kuyrukta bekliyorsan → kuyruktan çıkar.\n"
        "• Bekleme listesine katıldıysan → listeden çıkar.\n"
        "• Bekleme listesini sen başlattıysan → liste iptal edilir, diğer katılımcılar kuyruğa geri alınır.\n"
        "• Aktif challenge veya değerlendirme aşamasındaysan → kullanılamaz, bunun yerine challenge kanalındaki *Projeyi Bırak* butonunu kullan.\n\n"
        "*`/challenge list`*\n"
        "Kategorilere göre mevcut kuyruk doluluk durumunu gör.\n\n"
        "*`/challenge info`*\n"
        "Kendi challenge geçmişini görüntüle.\n\n"
        "*`/challenge submit`*\n"
        "_(Sadece challenge kanalında)_ Projeyi teslim et — 10 dakikalık teslim penceresi açılır.\n\n"
        "*`/challenge evaluate`*\n"
        "_(Sadece değerlendirme kanalında)_ Jüri puanlama formunu aç."
    )

    builder.add_divider()
    builder.add_header("⚖️ Jüri Komutları")

    builder.add_text(
        "*`/jury join`*\n"
        "Jüri kuyruğuna katıl. Bekleyen bir challenge varsa hemen atanırsın.\n\n"
        "*`/jury leave`*\n"
        "Jüri kuyruğundan çık.\n\n"
        "*`/jury list`*\n"
        "Jüri kuyruğundaki kişileri listele."
    )

    builder.add_divider()
    builder.add_context(["Jüri olarak katıldığın challenge'larda puanlama yapamazsın."])

    client.chat_postEphemeral(channel=channel_id, user=user_id, text="📖 Challenge Komutları", blocks=builder.build())


def handle_leave(client, user_id, channel_id):
    """Kullanıcıyı tüm kuyruklardan ve pending challenge'lardan çıkarır."""
    from ...core.queue.challenge_queue import QueueItem

    left_queue = False
    for q in service_manager.category_queues.values():
        if q.remove(user_id):
            left_queue = True

    left_pending = False
    with service_manager.pending_lock:
        for pid, pending in list(service_manager.pending_challenges.items()):
            if user_id not in pending["participants"]:
                continue

            is_initiator = pending["participants"][0] == user_id
            cat_label = pending["category"].value.replace("_", " ").title()

            message_ts = pending.get("message_ts")
            category = pending["category"]
            num = pending["num"]

            if is_initiator:
                # Başlatan kişi ayrılıyor → pending iptal, diğerlerini kuyruğa geri al
                others = [uid for uid in pending["participants"] if uid != user_id]
                del service_manager.pending_challenges[pid]
                left_pending = True

                q = service_manager.category_queues[category]
                for uid in others:
                    q.add(QueueItem(slack_id=uid))

                # Davet mesajını "iptal" olarak güncelle
                if message_ts:
                    try:
                        client.chat_update(
                            channel=channel_id,
                            ts=message_ts,
                            text=f"❌ {cat_label} Challenge — İptal Edildi",
                            blocks=[BlockBuilder.section(
                                text=f"❌ *{cat_label} Challenge* iptal edildi — başlatan kişi ayrıldı."
                            )]
                        )
                    except Exception:
                        pass

                # Ortak kanala bildirim
                if others:
                    mentions = " ".join(f"<@{uid}>" for uid in others)
                    client.chat_postMessage(
                        channel=channel_id,
                        text=f"{mentions}\n\n"
                             f"*{cat_label}* challenge bekleme listesi iptal edildi.\n"
                             f"Kuyruğa geri alındınız — yeni bir eşleşme olduğunda bilgilendirileceksiniz."
                    )
            else:
                # Katılan kişi ayrılıyor → listeden çıkar, davet mesajını güncelle
                pending["participants"].remove(user_id)
                left_pending = True
                current = len(pending["participants"])

                # Davet mesajını güncel kişi sayısıyla yeniden yaz
                if message_ts:
                    try:
                        remaining_needed = num - current
                        client.chat_update(
                            channel=channel_id,
                            ts=message_ts,
                            text=f"🚀 Aktif {cat_label} Challenge — {current}/{num} kişi",
                            blocks=[BlockBuilder.section(
                                text=f"*{current}/{num}* kişi hazır. "
                                     f"Hâlâ *{remaining_needed}* kişiye ihtiyaç var.\n\n"
                                     f"Katılmak için `/challenge join` komutunu yaz ve *{cat_label}* kategorisini seç."
                            )]
                        )
                    except Exception:
                        pass

            break  # Bir kullanıcı birden fazla pending'de olamaz

    if left_queue or left_pending:
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="👋 Kuyruktan/bekleme listesinden başarıyla ayrıldın."
        )

def handle_list(client, user_id, channel_id):
    """Tüm kuyrukların doluluk durumunu listeler."""
    builder = MessageBuilder().add_header("📊 Mevcut Kuyruk Durumları")
    
    any_waiting = False
    for cat, q in service_manager.category_queues.items():
        count = q.count()
        if count > 0:
            builder.add_text(f"• *{cat.value.upper()}*: _{count} kişi bekliyor_")
            any_waiting = True
            
    if not any_waiting:
        builder.add_text("📭 Şu anda tüm kuyruklar boş.")

    client.chat_postEphemeral(channel=channel_id, user=user_id, text="📊 Kuyruk Durumları", blocks=builder.build())

def handle_info(client, user_id, channel_id):
    """Kullanıcının kişisel challenge geçmişini DB'den çeker ve formatlanmış olarak gösterir."""
    # Status → emoji & label eşleşmesi
    STATUS_LABELS = {
        "started":            "🟡 Devam Ediyor",
        "completed":          "✅ Tamamlandı",
        "not_completed":      "❌ Tamamlanamadı",
        "in_evaluation":      "🔍 Değerlendirmede",
        "evaluated":          "🏆 Değerlendirildi",
        "evaluation_delayed": "⏳ Değerlendirme Gecikti",
        "not_started":        "⏸ Başlamadı",
    }

    async def _fetch():
        async with db.session(read_only=True) as session:
            repo = ChallengeRepository(session)
            return await repo.history_by_slack_id(user_id)

    try:
        challenges = run_async(_fetch())
    except Exception as e:
        _logger.error("[CMD] Failed to fetch history for %s: %s", user_id, e)
        client.chat_postEphemeral(
            channel=channel_id, user=user_id,
            text="⚠️ Geçmiş veriler şu an alınamıyor, lütfen tekrar deneyin."
        )
        return

    builder = MessageBuilder()
    builder.add_header(f"📋 Challenge Geçmişin")

    if not challenges:
        builder.add_text("_Henüz hiçbir meydan okumaya katılmadın._")
        client.chat_postEphemeral(channel=channel_id, user=user_id, text="📋 Challenge Geçmişin", blocks=builder.build())
        return

    # Kategoriye göre grupla
    from collections import defaultdict
    grouped: dict[str, list] = defaultdict(list)
    for ch in challenges:
        cat = ch.challenge_type.category.value if ch.challenge_type else "Bilinmiyor"
        grouped[cat].append(ch)

    for cat_value, items in grouped.items():
        cat_label = cat_value.replace("_", " ").title()
        builder.add_divider()
        builder.add_text(f"*📁 {cat_label}*")
        for ch in items:
            started = ch.challenge_started_at.strftime("%d %b %Y") if ch.challenge_started_at else "—"
            ended = ch.challenge_ended_at.strftime("%d %b %Y") if ch.challenge_ended_at else "—"
            status_label = STATUS_LABELS.get(ch.status.value, ch.status.value)
            score = f"  ·  Puan: *{ch.evaluation_score:.1f}*" if ch.evaluation_score else ""
            project_name = ch.challenge_type.name if ch.challenge_type else "—"
            github_url = (ch.meta or {}).get("submission", {}).get("github_url", "")
            github_part = f"  ·  <{github_url}|GitHub>" if github_url else ""
            builder.add_text(
                f"• {status_label}  ·  *{project_name}*  ·  Başlangıç: `{started}`  ·  Bitiş: `{ended}`{score}{github_part}"
            )

    builder.add_divider()
    builder.add_context([f"Toplam *{len(challenges)}* meydan okuma bulundu."])
    client.chat_postEphemeral(channel=channel_id, user=user_id, text="📋 Challenge Geçmişin", blocks=builder.build())
