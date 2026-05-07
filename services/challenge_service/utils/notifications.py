"""
Challenge servisi bildirimleri — admin vs topluluk ayrımı.

Admin kanalı (`SLACK_ADMIN_CHANNEL`): emoji yok, kısa etiket + kısaltmalar (CHG önekli).
Diğer kanallar (challenge özel kanal, ortak/komut kanalı vb.): emoji ve uzun metin kullanılabilir.

Mesaj önekleri: `packages.slack.service_prefixes` üç harflik kod (CHG).

Kanal türüne göre token seçimi:
  - Ortak/admin kanal  → bot_client  (mesajlar bot kimliğiyle gider)
  - Özel challenge/eval kanalları → user_client  (bot her kanalda üye olmayabilir)
"""
from __future__ import annotations

from packages.settings import get_settings
from packages.slack.blocks.builder import MessageBuilder
from packages.slack.service_prefixes import PREFIX_CHALLENGE, fmt as svc_fmt

from .slack_helpers import slack_helper
from ..logger import _logger


# --- Topluluk / genel günlük (emoji olabilir) -------------------------------------------------

def _clog(msg: str) -> str:
    return svc_fmt(PREFIX_CHALLENGE, msg)


# --- Admin günlük: emoji yok, TAG| özet ----------------------------------------------


def _admin_chg(tag: str, detail: str) -> str:
    """
    SLACK_ADMIN_CHANNEL için satır üretir. Emoji kullanılmaz; `tag` kısaltma (örn. YAP, SRB).
    """
    cleaned = " ".join((detail or "").split())
    return f"[CHG] {tag}| {cleaned}"


def _community_broadcast_channel() -> str:
    """Uzantılı duyurular: SLACK_ANNOUNCEMENT_CHANNEL tanımlıysa o, değilse SLACK_CHALLENGE_CHANNEL."""
    s = get_settings()
    ann = (s.slack_announcement_channel or "").strip()
    return ann or (s.slack_challenge_channel or "").strip()


# ---------------------------------------------------------------------------
# Shutdown bildirimleri
# ---------------------------------------------------------------------------


def notify_shutdown(
    registry,
    category_queues: dict,
    pending_lock,
    pending_challenges: dict,
) -> None:
    """
    Servis kapanmadan önce ilgili kanallara kısa bilgi; özet admin kanalına (kısaltmalı).
    registry ve queue'lar henüz temizlenmeden önce çağrılmalı.
    """
    s = get_settings()
    challenge_channel = s.slack_challenge_channel
    admin_channel = s.slack_admin_channel

    # 1. Aktif challenge kanalları — özel kanal → user_client (emoji kullanıcıya yönelik OK)
    for channel_id, record in registry.challenge_channels().items():
        if not record.members:
            continue
        mentions = " ".join(f"<@{uid}>" for uid in record.members)
        _safe_private(
            channel_id,
            f"{mentions}\n\n"
            + _clog("Servis kapanıyor; challenge kaydı korunuyor.") + "\n"
            + _clog("Komutlar kısa süre kullanılamayabilir; yeniden bağlanınca devam."),
        )

    # 2. Evaluation kanalları — user_client
    for channel_id, record in registry.evaluation_channels().items():
        all_members = list({*record.members, *record.jury})
        if not all_members:
            continue
        mentions = " ".join(f"<@{uid}>" for uid in all_members)
        _safe_private(
            channel_id,
            f"{mentions}\n\n"
            + _clog("Servis kapanıyor; değerlendirme kaydı korunuyor.") + "\n"
            + _clog("Komutlar kısa süre kullanılamayabilir."),
        )

    # 3. Kuyruk — ortak kanal (kısa)
    queued: list[tuple[str, str]] = []
    for cat, q in category_queues.items():
        cat_label = cat.value.replace("_", " ").title()
        for uid in q.get_order():
            queued.append((uid, cat_label))

    if queued:
        mentions = " ".join(f"<@{uid}>" for uid, _ in queued)
        lines = "\n".join(f"  - <@{uid}> — {cat}" for uid, cat in queued)
        _safe_public(
            challenge_channel,
            f"{mentions}\n\n"
            + _clog("Yeniden başlatma: kuyruk sıfırlandı.") + "\n"
            + _clog("Döndüğünüzde `/challenge join` ile tekrar kuyruğa girebilirsiniz.") + "\n\n"
            f"{lines}",
        )

    # 4. Pending gruplar — ortak kanal (kısa)
    with pending_lock:
        for _pid, p in list(pending_challenges.items()):
            if not p.get("participants"):
                continue
            mentions = " ".join(f"<@{uid}>" for uid in p["participants"])
            cat_label = p["category"].value.replace("_", " ").title()
            _safe_public(
                challenge_channel,
                f"{mentions}\n\n"
                + _clog(f"Bekleyen {cat_label} grubu yeniden başlatma nedeniyle iptal.") + "\n"
                + _clog("Tekrar `/challenge join` kullanabilirsiniz."),
            )

    # 5. Admin — kapanış (emoji yok)
    ch_count = len(registry.challenge_channels())
    ev_count = len(registry.evaluation_channels())
    q_count = sum(q.count() for q in category_queues.values())
    admin_lines = [
        _admin_chg("EVT", "svc_dn shutdown_notify"),
        _admin_chg("YAP", f"cnt_pch={ch_count} cnt_ech={ev_count} cnt_q={q_count}"),
        _admin_chg("SRB", "sock_stop proc_exit"),
    ]
    _safe_public(admin_channel, "\n".join(admin_lines))

    _logger.info("[NOTIFY] shutdown notifications sent")


# ---------------------------------------------------------------------------
# Startup: silinecek challenge'lar için bildirim
# ---------------------------------------------------------------------------


def notify_cancelled_challenges(
    cancel_data: list[tuple[str | None, list[str]]],
) -> None:
    """
    RESUME/FRESH temizliğinde silinecek challenge katılımcılarını bildirir.
    cancel_data: [(challenge_channel_id | None, [slack_id, ...])]
    """
    if not cancel_data:
        return

    s = get_settings()
    fallback_channel = s.slack_challenge_channel

    for channel_id, member_slack_ids in cancel_data:
        if not member_slack_ids:
            continue
        mentions = " ".join(f"<@{uid}>" for uid in member_slack_ids)
        text = (
            f"{mentions}\n\n"
            + _clog("Bu challenge servis yeniden başlatması nedeniyle iptal edildi.") + "\n"
            + _clog("Yeniden katılmak için `/challenge join` kullanın.")
        )
        if channel_id:
            _safe_private(channel_id, text)
        else:
            _safe_public(fallback_channel, text)

    _logger.info("[NOTIFY] cancelled challenge notifications sent (%d)", len(cancel_data))


# ---------------------------------------------------------------------------
# Startup bildirimleri
# ---------------------------------------------------------------------------


def notify_startup(registry) -> None:
    """
    Servis başladıktan ve registry dolduktan sonra.
    Topluluk kanalına kısa özet; admin kanalına operasyon günlüğü (kısaltmalı).
    """
    s = get_settings()
    challenge_channel = s.slack_challenge_channel
    admin_channel = s.slack_admin_channel

    # 1. Aktif challenge kanalları (özel)
    for channel_id, record in registry.challenge_channels().items():
        if not record.members:
            continue
        mentions = " ".join(f"<@{uid}>" for uid in record.members)
        _safe_private(
            channel_id,
            f"{mentions}\n\n"
            + _clog("Servis tekrar çevrimiçi; challenge devam edebilir."),
        )

    # 2. Evaluation kanalları (özel)
    for channel_id, record in registry.evaluation_channels().items():
        all_members = list({*record.members, *record.jury})
        if not all_members:
            continue
        mentions = " ".join(f"<@{uid}>" for uid in all_members)
        _safe_private(
            channel_id,
            f"{mentions}\n\n"
            + _clog("Servis tekrar çevrimiçi; değerlendirme süreci devam eder."),
        )

    # 3. Topluluk challenge kanalı — kısa
    ch_count = len(registry.challenge_channels())
    ev_count = len(registry.evaluation_channels())

    if ch_count or ev_count:
        status_line = _clog(
            f"Durum: aktif challenge={ch_count}, değerlendirme={ev_count}."
        )
    else:
        status_line = _clog("Durum: aktif challenge veya değerlendirme yok.")

    community_text = "\n".join(
        [
            _clog("Sistem aktif."),
            status_line,
            _clog("Komutlar: `/challenge join` · `/challenge start` · `/challenge list` · `/challenge help` · `/jury join`"),
        ]
    )
    _safe_public(challenge_channel, community_text)

    # 4. Admin — açılış (emoji yok)
    admin_text = "\n".join(
        [
            _admin_chg("EVT", "svc_up reg_ok"),
            _admin_chg("YAP", f"cnt_pch={ch_count} cnt_ech={ev_count}"),
            _admin_chg("SRB", "sock_listen mon_run"),
        ]
    )
    _safe_public(admin_channel, admin_text)

    _logger.info("[NOTIFY] startup notifications sent")


# ---------------------------------------------------------------------------
# Challenge başladı — admin günlük + toplulukta uzun duyuru
# ---------------------------------------------------------------------------


def notify_challenge_launched_admin(
    *,
    challenge_id: str,
    challenge_channel_id: str,
    category_label: str,
    challenge_type_id: str | None,
    challenge_type_name: str | None,
    points: int | None,
    participant_slack_ids: list[str],
) -> None:
    """Yeni challenge açıldığında admin kanalına günlük (emoji yok)."""
    s = get_settings()
    admin_channel = (s.slack_admin_channel or "").strip()
    if not admin_channel:
        return

    tid = challenge_type_id or "-"
    tname = challenge_type_name or "-"
    pts = str(points) if points is not None else "-"
    people = " ".join(f"<@{uid}>" for uid in participant_slack_ids) or "-"

    lines = [
        _admin_chg("EVT", f"launch_beg cid={challenge_id}"),
        _admin_chg("YAP", f"priv_ch pch={challenge_channel_id} cat={category_label}"),
        _admin_chg("YAP", f"db_ins tid={tid} tnm={tname} pts={pts}"),
        _admin_chg("YAP", "reg_up"),
        _admin_chg("SRB", "team_dev cmd_submit=/challenge_submit ttl=10m"),
        _admin_chg("KT", people),
    ]
    _safe_public(admin_channel, "\n".join(lines))


def notify_challenge_community_launch_long(
    *,
    challenge_id: str,
    challenge_channel_id: str,
    category_label: str,
    challenge_type_name: str | None,
    challenge_type_description: str | None,
    deadline_hours: int | None,
    points: int | None,
    participant_slack_ids: list[str],
) -> None:
    """
    Yeni challenge için topluluk/duyuru kanalında uzun açıklama (emoji kullanılabilir).
    Kanal: SLACK_ANNOUNCEMENT_CHANNEL varsa orası, yoksa SLACK_CHALLENGE_CHANNEL.
    """
    ch_out = _community_broadcast_channel()
    if not ch_out:
        return

    mentions = " ".join(f"<@{uid}>" for uid in participant_slack_ids) or "—"
    pname = challenge_type_name or "Henüz atanmamış şablon"

    desc = (challenge_type_description or "").strip()
    if len(desc) > 2200:
        desc = desc[:2199] + "…"

    hrs = deadline_hours if deadline_hours is not None else "—"
    pts = points if points is not None else "—"

    intro = (
        "Yeni bir challenge başladı. Aşağıdaki ekip, özel bir çalışma kanalında birlikte "
        "projeyi yürütüyor. Topluluktaki herkesin haberdar olması için bu mesaj özetliyor:"
    )

    builder = MessageBuilder()
    builder.add_header(f"{category_label} challenge başladı", emoji=True)
    builder.add_text(intro)
    builder.add_divider()
    builder.add_text(
        f"*Ekip*\n{mentions}\n\n"
        f"*Kategori*\n_{category_label}_\n\n"
        f"*Atanan proje (şablon)*\n*{pname}*\n\n"
        + (f"*Proje özeti*\n{desc}\n\n" if desc else "")
        + f"*Süre (şablon)*\n_{hrs}_ saat (deadline izleme aktif).\n\n"
        f"*Şablon puanı*\n_{pts}_ (tamamlayıp jüride değerlendiklerinde kullanılacak şablon ağırlığı).\n\n"
        "*Nasıl ilerliyor*\n"
        "• Takım kendi kapalı Slack kanalında çalışıyor; size görünmez, bu normal.\n"
        "• Görev teslim etmek için ekip içinde `/challenge submit` kullanılacak (10 dk’lık teslim penceresi).\n"
        "• Kendi geçmişiniz için `/challenge info` yazabilirsiniz.\n"
        "• Yeni challenge’a katılmak için `#challenge` (veya komutların tanımlandığı kanalda) `/challenge join`."
    )
    builder.add_context(
        [f"[CHG] ref_cid `{challenge_id}` · pch `{challenge_channel_id}` (özel kanal)"]
    )

    fallback = f"[CHG] Challenge başladı: {category_label} — {pname}. Ekip: {mentions}"

    try:
        slack_helper.post_public_message(channel_id=ch_out, text=fallback, blocks=builder.build())
    except Exception as exc:
        _logger.warning("[NOTIFY] community launch long failed (%s): %s", ch_out, exc)


# ---------------------------------------------------------------------------
# Teslim sonrası (eval kanalı açılışı) — admin
# ---------------------------------------------------------------------------


def notify_challenge_submitted_admin(
    *,
    challenge_id: str,
    archived_challenge_channel_id: str,
    eval_channel_id: str,
    submitted_by_slack_id: str,
    category_label: str,
    challenge_type_id: str | None,
    challenge_type_name: str | None,
    points: int | None,
    github_url_trim: str,
) -> None:
    s = get_settings()
    admin_ch = (s.slack_admin_channel or "").strip()
    if not admin_ch:
        return

    tid = challenge_type_id or "-"
    tnm = challenge_type_name or "-"
    pts = str(points) if points is not None else "-"
    gh = (github_url_trim or "-")[:160]

    lines = [
        _admin_chg("EVT", f"submit_ok cid={challenge_id}"),
        _admin_chg("YAP", f"pch_arch pch={archived_challenge_channel_id}"),
        _admin_chg("YAP", f"ech_open ech={eval_channel_id}"),
        _admin_chg("YAP", f"sub_by uid={submitted_by_slack_id} url={gh}"),
        _admin_chg("INF", f"cat={category_label} tid={tid} tnm={tnm} tpl_pts={pts}"),
        _admin_chg("SRB", "jury_assign cmd_eval=/challenge_evaluate"),
    ]
    _safe_public(admin_ch, "\n".join(lines))


# ---------------------------------------------------------------------------
# Kapatılma — teslim edilmemiş veya iptal — admin
# ---------------------------------------------------------------------------


def notify_challenge_closed_admin(
    *,
    challenge_id: str,
    reason: str,
    archived_channel_id: str | None,
    actor_slack_id: str | None,
    category_label: str | None,
    challenge_type_id: str | None,
    challenge_type_name: str | None,
) -> None:
    """reason: surrender | deadline | (ileride başka kodlar)."""
    s = get_settings()
    admin_ch = (s.slack_admin_channel or "").strip()
    if not admin_ch:
        return

    ach = archived_channel_id or "-"
    act = actor_slack_id or "-"
    cat = category_label or "-"
    tid = challenge_type_id or "-"
    tnm = challenge_type_name or "-"

    lines = [
        _admin_chg("EVT", f"ch_end cid={challenge_id} rsn={reason}"),
        _admin_chg("YAP", f"pch_arch pch={ach}"),
        _admin_chg("INF", f"cat={cat} tid={tid} tnm={tnm} actor={act}"),
        _admin_chg("SRB", "noop db_st=NOT_COMPLETED"),
    ]
    _safe_public(admin_ch, "\n".join(lines))


# ---------------------------------------------------------------------------
# Değerlendirme tamamlandı — admin
# ---------------------------------------------------------------------------


def notify_challenge_eval_completed_admin(
    *,
    challenge_id: str,
    evaluation_channel_id: str | None,
    average_score: float,
    challenge_type_id: str | None,
    challenge_type_name: str | None,
) -> None:
    s = get_settings()
    admin_ch = (s.slack_admin_channel or "").strip()
    if not admin_ch:
        return

    ech = evaluation_channel_id or "-"
    tid = challenge_type_id or "-"
    tnm = challenge_type_name or "-"
    score_s = f"{average_score:.2f}"

    lines = [
        _admin_chg("EVT", f"eval_done cid={challenge_id}"),
        _admin_chg("YAP", f"jury_full scr={score_s}"),
        _admin_chg("YAP", f"ech_arch ech={ech}"),
        _admin_chg("INF", f"tid={tid} tnm={tnm}"),
        _admin_chg("SRB", "db_st=EVALUATED pub_ann_ok"),
    ]
    _safe_public(admin_ch, "\n".join(lines))


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _safe_public(channel_id: str, text: str) -> None:
    if not (channel_id or "").strip():
        return
    try:
        slack_helper.post_public_message(channel_id, text)
    except Exception as exc:
        _logger.warning("[NOTIFY] public post failed (channel=%s): %s", channel_id, exc)


def _safe_private(channel_id: str, text: str) -> None:
    if not (channel_id or "").strip():
        return
    try:
        slack_helper.post_message(channel_id, text)
    except Exception as exc:
        _logger.warning("[NOTIFY] private post failed (channel=%s): %s", channel_id, exc)
