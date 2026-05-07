"""
`/help` desteği ve `/event help` için paylaşılan metin blokları.

Türkçe: komutların yanı sıra akış özeti içerir.
"""

from __future__ import annotations

from slack_sdk.errors import SlackApiError

from packages.slack.blocks.builder import MessageBuilder

_HELP_REGISTERED = False


def english_help_mrkdwn() -> str:
    return (
        "*İngilizce pratik —* `/english`\n\n"
        "*Komut*\n"
        "`/english` — Oturumu başlatır veya sıfırlayıp seçimleri baştan yapar.\n\n"
        "*Çalışma mantığı*\n"
        "• Slash komutu sonra her şey düğmeli seçim ve (yazı modunda) metin tesliminden oluşur.\n"
        "• Seviye seçilir (Beginner / Intermediate / Advanced), ardından mod: *Writing* veya *Quiz*.\n"
        "• Writing: görev tipi (konuya göre yazı veya çeviri) seçilir; bot görev ve talimatları "
        "(genelde kanal içinde size özel) iletir; oturum «yazı bekliyor» durumuna geçer.\n"
        "• Yazınızı teslim etmek için kanala *sıradan bir mesaj* gönderirsiniz "
        "`/` ile başlayan satırlar komut olarak sayılıp yazı olarak değerlendirilmez).\n"
        "• Quiz: sorular seçenek düğmeleriyle izlenir; cevaplardan sonra sonraki adım düğmelerle gelir.\n"
        "• Tekrar `/english`: önceki seviye / mod bilgisi ve ara görevler temizlenir; sıfırdan seçilir."
    )


def event_help_mrkdwn(limit_note: str = "") -> str:
    """`/event help` ile `/help` içinde kullanılacak gövde (başlık dışında)."""
    ln = limit_note.strip()
    ln_block = (ln + "\n\n") if ln else ""
    return (
        "*Etkinlikler —* `/event` *…*\n\n"
        "*Komutların çalıştığı yer*\n"
        "Çoğu alt komut, yapılandırmaya göre yalnızca *belirlenen duyuru kanalında* çalışır; "
        "başka kanaldan yazarsanız kısıtlama uyarısı alırsınız.\n\n"
        "*Akış özeti*\n"
        "`/event create` ile modal açılır; başvuru oluşturulur ve bildiriler / zamanlama süreçleri "
        "(scheduler) üzerinden yürür. Yaklaşan etkinliklere `/event list` ile bakılır, ilgi için "
        "`/event add_me`, kendi oluşturduklarınızı `/event my_list`; düzenlemek için `/event update`, "
        "iptal için `/event cancel` kullanılır.\n\n"
        f"{ln_block}"
        "*Komutlar*\n"
        "*`/event create`* — Yeni etkinlik talebi; form/modal ile girilir.\n"
        "*`/event list`* — Bu ay yaklaşan etkinlikler.\n"
        "*`/event my_list`* — Sizin oluşturduğunuz talepler.\n"
        "*`/event history`* — Geçmiş etkinlikleri listeler.\n"
        "*`/event add_me`* — Önümüzdeki döneme ait bildirilmiş etkinliklere tek seferlik ilgi formu.\n"
        "*`/event update`* — Sahiplendiğiniz etkinlikleri güncelleme modali.\n"
        "*`/event cancel`* — İptal formu/modali.\n"
        "*`/event help`* — Etkinlik komut özeti.\n\n"
        "_Etkinlik kimliği için sıklıkla `/event list` kullanırsınız._"
    )


def build_global_help_blocks() -> list:
    """`/help` mesaj blokları."""
    mb = MessageBuilder()
    mb.add_header("Topluluk yardımı")
    mb.add_text(
        english_help_mrkdwn()
        + "\n\n"
        + event_help_mrkdwn()
        + "\n\n"
        "*Diğer Slack komutları*\n"
        "Challenge, özet ve özellik isteği işlemleri ayrı slash komutlarıyla tanımlıdır "
        "`/challenge`, `/channel-summary`, `/summary`, `/cemilimyapar` vb.)."
    )
    mb.add_divider()
    mb.add_context(
        [
            "Bu mesaja her yerden `/help` yazarak yeniden bakabilirsiniz; "
            "etkinlik alt komutları için duyuru kanalı kısıtlamasına dikkat edin.",
        ]
    )
    return mb.build()


def _post_ephemeral_help(
    client,
    channel_id: str,
    user_id: str,
    blocks: list,
    fallback: str,
) -> None:
    kw: dict = {
        "channel": channel_id,
        "user": user_id,
        "text": fallback or " ",
        "blocks": blocks,
    }
    try:
        client.chat_postEphemeral(**kw)
    except SlackApiError as exc:
        err = exc.response.get("error") if exc.response else None
        if err not in ("is_archived", "channel_not_found", "not_in_channel"):
            raise
        try:
            dm = client.conversations_open(users=user_id)["channel"]["id"]
            client.chat_postMessage(channel=dm, text=fallback or " ", blocks=blocks)
        except Exception:
            raise exc


def setup_community_help_command() -> None:
    """Aynı process içinde yalnızca bir kez `/help` kaydedilir."""
    global _HELP_REGISTERED
    if _HELP_REGISTERED:
        return
    _HELP_REGISTERED = True

    from packages.slack.client import slack_client

    app = slack_client.app
    fallback = (
        "Yardım: `/english`, `/event …`, `/challenge`. "
        "Ayrıntılı içerik Slack blok görünümünde gösterilir."
    )

    @app.command("/help")
    def slash_help(ack, body, client):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id") or ""
        if not user_id or not channel_id:
            return
        _post_ephemeral_help(
            client,
            channel_id,
            user_id,
            build_global_help_blocks(),
            fallback,
        )
