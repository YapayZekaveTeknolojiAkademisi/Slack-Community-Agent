from typing import Dict, List, Optional

from .builder import BlockBuilder, Formatter


class Layouts:
    """
    Akademi Topluluk Asistanı için hazır, tutarlı UI şablonları.
    Her metod bir BLOCK LİSTESİ döner.
    """

    @staticmethod
    def error(title: str, message: str, details: Optional[str] = None) -> List[Dict]:
        """Kırmızı temalı (emoji ile) hata mesajı layoutu."""
        blocks = [BlockBuilder.header(f"🛑 {title}"), BlockBuilder.section(message)]
        if details:
            blocks.append(
                BlockBuilder.context([f"ℹ️ *Hata Detayı:* {Formatter.code(details)}"])
            )
        return blocks

    @staticmethod
    def success(
        title: str,
        message: str,
        action_text: Optional[str] = None,
        action_id: Optional[str] = None,
    ) -> List[Dict]:
        """Yeşil temalı başarı mesajı layoutu."""
        blocks = [BlockBuilder.header(f"✅ {title}"), BlockBuilder.section(message)]
        if action_text and action_id:
            blocks.append(
                BlockBuilder.actions(
                    [BlockBuilder.button(action_text, action_id, style="primary")]
                )
            )
        return blocks

    @staticmethod
    def info_card(
        title: str,
        description: str,
        icon: str = "ℹ️",
        fields: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Bilgilendirme kartı (örn. profil, yardım içeriği)."""
        blocks = [
            BlockBuilder.header(f"{icon} {title}"),
            BlockBuilder.section(description),
        ]
        if fields:
            blocks.append(BlockBuilder.section(fields=fields))
        return blocks

    @staticmethod
    def challenge_invitation(
        title: str,
        description: str,
        theme: str,
        difficulty: str,
        action_id: str,
        challenge_id: str,
    ) -> List[Dict]:
        """Challenge katılım ilanı layoutu. Buton tıklanınca challenge_id action_value olarak gelir."""
        return [
            BlockBuilder.header(f"🚀 Yeni Challenge: {title}"),
            BlockBuilder.section(description),
            BlockBuilder.section(
                fields=[f"*Tema:* {theme}", f"*Zorluk:* {difficulty}"]
            ),
            BlockBuilder.divider(),
            BlockBuilder.actions(
                [
                    BlockBuilder.button(
                        "Katılmak İstiyorum! ✨",
                        action_id,
                        value=challenge_id,
                        style="primary",
                    ),
                    BlockBuilder.button(
                        "Detaylar 🔍", f"details_{action_id}", value=challenge_id
                    ),
                ]
            ),
        ]

    @staticmethod
    def summary_card(title: str, summary_text: str) -> List[Dict]:
        """Özet içeriğini gösteren layout."""
        return [
            BlockBuilder.header(f"📚 {title}"),
            BlockBuilder.section(summary_text),
            BlockBuilder.divider(),
            BlockBuilder.context(
                ["🪄 *Groq AI tarafından asistanınız Cemil için hazırlanmıştır.*"]
            ),
        ]

    @staticmethod
    def feature_request_success(text_preview: str) -> List[Dict]:
        """Başarılı özellik talebi gönderimi."""
        # Metin çok uzunsa kırpıyoruz
        preview = (
            text_preview if len(text_preview) < 150 else text_preview[:147] + "..."
        )
        return [
            BlockBuilder.header("✅ Fikrin Kaydedildi!"),
            BlockBuilder.section(
                f"Müthiş bir fikir! Ekibimiz ve yapay zeka algoritmamız tarafından değerlendirilecek.\n\n> _{preview}_"
            ),
        ]

    @staticmethod
    def feature_request_similar(
        existing_text: str, request_id: str, pending_id: str
    ) -> List[Dict]:
        """Benzer özellik talebi bulunduğunda çıkan uyarı ve butonlar."""
        return [
            BlockBuilder.header("⚠️ Benzer Bir Fikrin Var"),
            BlockBuilder.section(
                f"Bu hafta daha önce bu fikre çok benzer bir talepte bulunmuşsun:\n\n> {existing_text}\n\n"
                "Fikrinde değişiklik yapmak ister misin? (Haftalık hakkını korumuş olursun.)"
            ),
            BlockBuilder.actions(
                [
                    BlockBuilder.button(
                        "✏️ Düzenle",
                        "feature_edit_yes",
                        value=f"{request_id}|{pending_id}",
                        style="primary",
                    ),
                    BlockBuilder.button(
                        "🆕 Hayır, yeni fikrim farklı",
                        "feature_edit_no",
                        value=pending_id,
                    ),
                ]
            ),
        ]

    @staticmethod
    def feature_request_exact_match(existing_text: str, request_id: str) -> List[Dict]:
        """Çok yüksek benzerlik oranında çıkan kesin eşleşme uyarısı ve butonlar."""
        return [
            BlockBuilder.header("⚠️ Talebin Çok Benzer"),
            BlockBuilder.section(
                f"Bu fikri veya neredeyse aynısını zaten iletmişsiniz:\n\n> {existing_text}\n\n"
                "İsterseniz eskisini düzenleyebilirsiniz veya bu işlemi iptal edebilirsiniz."
            ),
            BlockBuilder.actions(
                [
                    BlockBuilder.button(
                        "✏️ Düzenle",
                        "feature_edit_yes",
                        value=f"{request_id}|None",
                        style="primary",
                    ),
                    BlockBuilder.button(
                        "❌ Vazgeç",
                        "feature_edit_cancel",
                        value="ignore",
                    ),
                ]
            ),
        ]

    @staticmethod
    def feature_request_quota_exceeded(used: int, max_quota: int) -> List[Dict]:
        """Haftalık submit kotası aşımında çıkan uyarı."""
        return [
            BlockBuilder.header("❌ Haftalık Hakkın Doldu"),
            BlockBuilder.section(
                f"Spam'i önlemek için sistemimiz bu hafta toplam *{max_quota}* fikir göndermene izin veriyor ve sen *{used}* hakkını da kullandın.\n"
                "Lütfen yeni parlak fikirlerini haftaya bizimle paylaş! 💡"
            ),
        ]

    @staticmethod
    def feature_request_report(report_text: str) -> List[Dict]:
        """Haftalık özellik kümeleme raporu layout'u (3000 karakter sınırına duyarlı)."""
        blocks = [BlockBuilder.header("📊 Haftalık Özellik Talepleri Raporu")]

        lines = report_text.split("\n")
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > 2900:
                if current_chunk:
                    blocks.append(BlockBuilder.section(current_chunk.strip()))
                current_chunk = line + "\n"
                # Fallback: Eger tek satir limiti asiyorsa
                while len(current_chunk) > 2900:
                    blocks.append(BlockBuilder.section(current_chunk[:2900]))
                    current_chunk = current_chunk[2900:]
            else:
                current_chunk += line + "\n"

        if current_chunk.strip():
            blocks.append(BlockBuilder.section(current_chunk.strip()))

        blocks.append(BlockBuilder.divider())
        return blocks

    @staticmethod
    def feature_cluster_details(
        cluster_id: int, label: str, requests: list
    ) -> List[Dict]:
        """Bir özelliğe ait tüm talepleri listeleyen admin detay layout'u."""
        blocks = [
            BlockBuilder.header(f"🔍 Cluster #{cluster_id} Detayları"),
            BlockBuilder.section(
                f"*Küme Adı:* {label}\n*Toplam Talep:* {len(requests)}"
            ),
        ]

        items_text = ""
        for i, req in enumerate(requests, 1):
            fraud_marker = " ⚠️" if req.fraud_score and req.fraud_score > 0.8 else ""
            line_text = f"*{i}.* <@{req.user_id}>{fraud_marker}: {req.request_raw}\n"

            if len(items_text) + len(line_text) > 2900:
                blocks.append(BlockBuilder.section(items_text.strip()))
                items_text = line_text
            else:
                items_text += line_text

        if items_text.strip():
            blocks.append(BlockBuilder.section(items_text.strip()))

        blocks.append(BlockBuilder.divider())
        return blocks

    @staticmethod
    def feature_request_modal(channel_id: str = "") -> Dict:
        """
        /cemilimyapar komutuyla açılan özellik talebi modal'ı.
        Dönen değer bir blok listesi değil, modal dict'idir (views_open'a verilir).
        """
        return {
            "type": "modal",
            "callback_id": "feature_request_modal",
            "private_metadata": channel_id,
            "title": {"type": "plain_text", "text": "Özellik Talebi", "emoji": True},
            "submit": {"type": "plain_text", "text": "Gönder 🚀", "emoji": True},
            "close": {"type": "plain_text", "text": "İptal", "emoji": True},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "👋 *Cemil'e bir özellik talebi gönder!*\n"
                            "Topluluk asistanına ne eklenmesini isterdin? "
                            "Fikrin haftalık raporlarda değerlendirilecek."
                        ),
                    },
                },
                {"type": "divider"},
                {
                    "type": "input",
                    "block_id": "feature_input_block",
                    "label": {
                        "type": "plain_text",
                        "text": "Fikrin nedir?",
                        "emoji": True,
                    },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "feature_text_input",
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Örnek: Haftalık challenge özetlerini DM olarak al…",
                        },
                        "min_length": 10,
                        "max_length": 500,
                    },
                },
            ],
        }

    @staticmethod
    def feature_request_edit_modal(
        existing_text: str, request_id: str, channel_id: str = ""
    ) -> Dict:
        """
        'Düzenle' butonuyla açılan düzenleme modal'ı.
        request_id, private_metadata olarak saklanır.
        Dönen değer bir blok listesi değil, modal dict'idir (views_open'a verilir).
        """
        return {
            "type": "modal",
            "callback_id": "feature_request_edit_modal",
            "private_metadata": f"{request_id}|{channel_id}",
            "title": {"type": "plain_text", "text": "✏️ Fikri Düzenle", "emoji": True},
            "submit": {"type": "plain_text", "text": "✅ Güncelle", "emoji": True},
            "close": {"type": "plain_text", "text": "❌ Vazgeç", "emoji": True},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Mevcut fikrin aşağıda gösteriliyor. Düzenleyip güncelleyebilirsin!",
                    },
                },
                {"type": "divider"},
                {
                    "type": "input",
                    "block_id": "feature_input_block",
                    "label": {
                        "type": "plain_text",
                        "text": "Güncel fikrin:",
                        "emoji": True,
                    },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "feature_text_input",
                        "multiline": True,
                        "initial_value": existing_text,
                        "min_length": 10,
                        "max_length": 500,
                    },
                },
            ],
        }
