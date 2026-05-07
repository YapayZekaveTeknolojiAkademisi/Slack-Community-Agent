# Packages Rehberi

[← README](../README.md)

`packages/` altındaki yeniden kullanılabilir kütüphane modüllerinin kullanım dokümantasyonu.

---

## İçindekiler

- [Logger](#logger)
- [Database](#database)
- [Slack](#slack)
- [SMTP](#smtp)
- [Settings](#settings)

---

## Logger

**Konum:** `packages/logger/`

Thread-safe, non-blocking loglama sistemi. `QueueHandler` + `QueueListener` mimarisiyle ana thread'i bloke etmez.

### Başlatma

Servis giriş noktasında **bir kez** çağrılır:

```python
from packages.logger.manager import start_logging

LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "system": {"()": "packages.logger.formatters.SystemMessageFormatter"},
        "error":  {"()": "packages.logger.formatters.ErrorMessageFormatter"},
        "api":    {"()": "packages.logger.formatters.ApiMessageFormatter"},
        "queue":  {"()": "packages.logger.formatters.QueueMessageFormatter"},
    },
    "filters": {
        "system_filter": {"()": "packages.logger.filters.SystemFilter"},
        "error_filter":  {"()": "packages.logger.filters.ErrorFilter"},
        "api_filter":    {"()": "packages.logger.filters.ApiFilter"},
        "queue_filter":  {"()": "packages.logger.filters.QueueFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "system",
            "filters": ["system_filter"],
        },
        "error_console": {
            "class": "logging.StreamHandler",
            "formatter": "error",
            "filters": ["error_filter"],
        },
    },
    "root": {"level": "DEBUG", "handlers": ["console", "error_console"]},
    "loggers": {
        "my_service": {"level": "DEBUG", "propagate": True},
    },
}

start_logging(LOG_CONFIG)
```

### Logger Alma

```python
import logging

logger = logging.getLogger("my_service.module")
logger.info("Servis başlatıldı")
logger.warning("Dikkat: bağlantı yavaş")
logger.error("Hata oluştu", exc_info=True)
```

> `start_logging()` çağrılmadan `logging.getLogger()` kullanmak güvenlidir —
> sadece QueueListener aktif olmaz, doğrudan handler'lara düşer.

### Durdurma

Servis kapanışında çağrılır (veya `atexit` ile otomatik çalışır):

```python
from packages.logger.manager import stop_logging
stop_logging()
```

### Filtreler

| Filtre | Ne Geçirir |
|--------|-----------|
| `SystemFilter` | `api` ve `queue` extra alanı olmayan tüm kayıtlar |
| `ErrorFilter` | Sadece `ERROR` ve üstü seviyeler |
| `ApiFilter` | `extra={"api": {...}}` içeren kayıtlar |
| `QueueFilter` | `extra={"queue": {...}}` içeren kayıtlar |

### Formatter'lar

#### `SystemMessageFormatter`
Genel loglar için sade format:
```
2026-04-01 12:00:00 [i] Servis başlatıldı
2026-04-01 12:00:01 [X] Bağlantı hatası
```

İkonlar: `[>]` DEBUG · `[i]` INFO · `[*]` WARNING · `[X]` ERROR · `[!]` CRITICAL

#### `ErrorMessageFormatter`
Hata kayıtları için JSON format (dosyaya yazmak için idealdir):
```json
{
  "timestamp": "2026-04-01 12:00:00",
  "level": "ERROR",
  "message": "DB bağlantısı kesildi",
  "location": [{"file": "manager.py", "function": "connect", "line": 42}],
  "exception": {"type": "ConnectionError", "message": "timeout"}
}
```

#### `ApiMessageFormatter`
API çağrı logları için — `extra={"api": {...}}` ile kullanılır:
```python
logger.info("API", extra={"api": {"TYPE": "POST", "Route": "/submit", "status": 200, "time": "12ms"}})
# POST --> /submit (200) (12ms)
```

#### `QueueMessageFormatter`
Kuyruk operasyonları için — `extra={"queue": {...}}` ile kullanılır:
```python
logger.debug("Queue", extra={"queue": {"name": "learn", "size": 3, "action": "pop", "value": "U123"}})
# learn (3) -- pop -- U123
```

---

## Database

**Konum:** `packages/database/`

Async SQLAlchemy 2.x + PostgreSQL (asyncpg). Repository pattern ile clean data access katmanı.

### Başlatma

```python
from packages.database.manager import db

# Servis başlangıcında bir kez çağrılır
db.initialize()

# Servis kapanışında
await db.shutdown()
```

### Session Kullanımı

Her DB işlemi için context manager ile session alınır. Transaction otomatik yönetilir.

#### Yazma (varsayılan)

```python
from packages.database.manager import db
from packages.database.models.challenge import Challenge, ChallengeStatus
from packages.database.repository.challenge import ChallengeRepository

async with db.session() as session:
    repo = ChallengeRepository(session)
    challenge = Challenge(
        creator_slack_id="U123456",
        status=ChallengeStatus.STARTED,
    )
    await repo.create(challenge)
    # session.begin() bloğundan çıkınca otomatik commit
```

#### Okuma (read-only)

```python
async with db.session(read_only=True) as session:
    repo = ChallengeRepository(session)
    challenges = await repo.list_started()
    for c in challenges:
        print(c.id, c.status)
    # SET TRANSACTION READ ONLY — DB seviyesinde korumalı
```

#### Hata Yönetimi

Exception fırlarsa session otomatik rollback yapılır:

```python
async with db.session() as session:
    repo = ChallengeRepository(session)
    challenge = await repo.get("CHL-nonexistent")
    if not challenge:
        raise ValueError("Challenge bulunamadı")  # → otomatik rollback
```

---

### Modeller

#### `ChallengeType` — Challenge şablonları

```python
from packages.database.models.challenge import ChallengeType, ChallengeCategory

challenge_type = ChallengeType(
    category=ChallengeCategory.PRACTICE,
    name="REST API Geliştirme",
    description="FastAPI ile CRUD endpoint'leri",
    deadline_hours=24,
    points=52,
    checklist=["README mevcut", "Testler yazıldı", "Deploy edildi"],
    meta={"difficulty": "intermediate"},
)
```

#### `Challenge` — Ana challenge kaydı

```python
from packages.database.models.challenge import Challenge, ChallengeStatus

challenge = Challenge(
    challenge_type_id="CHT-...",
    creator_slack_id="U123456",
    status=ChallengeStatus.STARTED,
    challenge_channel_id="C987654",
    meta={"submission": {"github_url": "https://...", "description": "..."}},
)
```

#### `ChallengeTeamMember` / `ChallengeJuryMember`

```python
from packages.database.models.challenge import ChallengeTeamMember, ChallengeJuryMember

# Takım üyesi
member = ChallengeTeamMember(
    challenge_id=challenge.id,
    user_id="SLU-...",   # slack_users.id (opsiyonel)
    slack_id="U123456",  # doğrudan Slack ID
)

# Jüri üyesi
jury = ChallengeJuryMember(
    challenge_id=challenge.id,
    user_id="SLU-...",
    slack_id="U789012",
)
```

#### `SlackUser`

```python
from packages.database.models.slack import SlackUser

user = SlackUser(
    slack_id="U123456",
    username="ahmet",
    display_name="Ahmet Yılmaz",
    email="ahmet@example.com",
    is_bot=False,
    is_active=True,
)
```

---

### Repository'ler

Tüm repository'ler `BaseRepository[T]`'dan türer. Temel CRUD ücretsiz gelir:

```python
repo.get(id)          # → T | None
repo.get_all()        # → Sequence[T]
repo.count()          # → int
repo.create(entity)   # → T  (flush yapar, ID atar)
repo.update(entity)   # → T  (flush yapar)
repo.delete(id)       # → bool
```

#### `ChallengeRepository` — Özel sorgular

```python
async with db.session(read_only=True) as session:
    repo = ChallengeRepository(session)

    # Duruma göre listeleme (takım + jüri + tip ilişkileriyle)
    started      = await repo.list_started()
    completed    = await repo.list_completed()
    in_eval      = await repo.list_in_evaluation()
    evaluated    = await repo.list_evaluated()
    delayed      = await repo.list_evaluation_delayed()
    not_done     = await repo.list_not_completed()
    not_started  = await repo.list_not_started()

    # Kullanıcının geçmişi (başlangıç tarihine göre DESC)
    history = await repo.history_by_slack_id("U123456")
    for c in history:
        print(c.challenge_type.name, c.status, c.evaluation_score)
```

#### `ChallengeTypeRepository` — Akıllı atama

```python
async with db.session(read_only=True) as session:
    repo = ChallengeTypeRepository(session)

    # Katılımcıların daha önce yapmadığı bir type seç
    challenge_type = await repo.pick_random_for_participants(
        category=ChallengeCategory.LEARN,
        participant_slack_ids=["U123", "U456"],
    )
    # Hepsi yapılmışsa rastgele herhangi birini döner
    # Hiç type yoksa None döner
```

#### `SlackUserRepository` — Upsert

```python
async with db.session() as session:
    repo = SlackUserRepository(session)

    # Varsa getir, yoksa oluştur
    user = await repo.get_or_create(
        slack_id="U123456",
        username="ahmet",
        display_name="Ahmet Yılmaz",
    )

    # Slack ID ile doğrudan ara
    user = await repo.get_by_slack_id("U123456")
```

---

### Model Mixinleri

Tüm modeller şu mixin'leri kullanır:

```python
# IDMixin — prefix'li UUID primary key
# Örnek: "CHL-550e8400-e29b-41d4-a716-446655440000"
class Challenge(Base, IDMixin, TimestampMixin):
    __prefix__ = "CHL"
    ...

# TimestampMixin — otomatik created_at / updated_at
# Python seviyesinde default — server_default değil
```

---

## Slack

**Konum:** `packages/slack/`

Slack Bolt + SDK sarmalayıcısı. Singleton `slack_client` nesnesi üzerinden erişilir.

### İstemci Nesneleri

```python
from packages.slack.client import slack_client

# Bolt uygulaması — handler kaydı için
app = slack_client.app

# Bot WebClient — genel mesajlaşma, kanal yönetimi
bot = slack_client.bot_client

# User WebClient — özel kanal oluşturma, arşivleme
user = slack_client.user_client

# Socket Mode handler — servisi başlatır (blocking)
slack_client.socket_handler.start()
```

**Bot vs User client farkı:**

| İşlem | Bot Client | User Client |
|-------|-----------|-------------|
| Mesaj gönderme | ✓ | - |
| Public kanal oluşturma | ✓ | - |
| **Private kanal oluşturma** | - | **✓** |
| **Kanal arşivleme** | - | **✓** |
| Kullanıcı bilgisi | ✓ | - |

---

### Handler Kaydetme (Bolt)

```python
from packages.slack.client import slack_client

app = slack_client.app

# Slash komut
@app.command("/challenge")
def handle_challenge(ack, command, client):
    ack()
    # ...

# Buton aksiyonu
@app.action("join_challenge")
def handle_join(ack, body, client):
    ack()
    # ...

# Modal submit
@app.view("challenge_modal")
def handle_modal(ack, body, view, client):
    ack()
    # ...

# Mesaj eventi
@app.event("message")
def handle_message(event, client):
    # ...
```

---

### Mesaj Gönderme — `ChatManager`

```python
from packages.slack.commands.chat import ChatManager

chat = ChatManager(slack_client.bot_client)

# Kanala mesaj
chat.post_message(channel="C123", text="Merhaba!")

# Block Kit ile zengin mesaj
from packages.slack.blocks.builder import MessageBuilder
blocks = (
    MessageBuilder()
    .add_header("Challenge Başladı!")
    .add_text("Takım oluşturuldu. Başarılar!")
    .add_button("Detaylar", action_id="view_details", style="primary")
    .build()
)
chat.post_message(channel="C123", text="Challenge başladı", blocks=blocks)

# Sadece o kullanıcıya görünür mesaj
chat.post_ephemeral(channel="C123", user="U456", text="Bu mesaj sadece sana görünür")

# Mesaj güncelle
chat.update(channel="C123", ts="1234567890.123", text="Güncellendi")

# Mesaj sil
chat.delete(channel="C123", ts="1234567890.123")

# Zamanlanmış mesaj
import time
chat.schedule_message(channel="C123", post_at=int(time.time()) + 3600, text="1 saat sonra")
```

---

### Kanal Yönetimi — `ConversationManager`

```python
from packages.slack.commands.conversations import ConversationManager

# Private kanal için user_client kullanılır
conv = ConversationManager(slack_client.user_client)
# Public kanal için bot_client yeterlidir
conv_bot = ConversationManager(slack_client.bot_client)

# Private kanal oluştur
resp = conv.create(name="challenge-learn-abc123", is_private=True)
channel_id = resp["channel"]["id"]

# Kullanıcı davet et
conv.invite(channel=channel_id, users=["U123", "U456", "U789"])

# Kanal arşivle
conv.archive(channel=channel_id)

# Kanal üyelerini getir
resp = conv_bot.members(channel=channel_id)
members = resp["members"]

# Kanal bilgisi
info = conv_bot.info(channel=channel_id)
```

---

### Modal (View) Yönetimi — `ViewManager`

```python
from packages.slack.commands.views import ViewManager

views = ViewManager(slack_client.bot_client)

# Modal aç
views.open(
    trigger_id=body["trigger_id"],
    view={
        "type": "modal",
        "callback_id": "my_modal",
        "title": {"type": "plain_text", "text": "Form"},
        "submit": {"type": "plain_text", "text": "Gönder"},
        "blocks": [...],
    }
)

# Modal güncelle
views.update(view={...}, view_id="V123")

# Home Tab yayınla
views.publish(user_id="U123", view={"type": "home", "blocks": [...]})
```

---

### Block Kit — `BlockBuilder` ve `MessageBuilder`

#### `BlockBuilder` — Tek blok üretir

```python
from packages.slack.blocks.builder import BlockBuilder, Formatter

# Başlık
BlockBuilder.header("Merhaba Dünya")

# Metin bölümü
BlockBuilder.section("Bu bir *kalın* metin içerir")

# Yan yana alanlar
BlockBuilder.section(fields=["*Alan 1:* Değer 1", "*Alan 2:* Değer 2"])

# Buton içeren aksiyonlar
BlockBuilder.actions([
    BlockBuilder.button("Onayla", "confirm_btn", style="primary"),
    BlockBuilder.button("İptal",  "cancel_btn",  style="danger"),
])

# Bağlam (küçük yazı)
BlockBuilder.context(["Son güncelleme: <!date^1234567890^{date_num}|...>"])

# Ayırıcı
BlockBuilder.divider()
```

#### `Formatter` — mrkdwn metni

```python
from packages.slack.blocks.builder import Formatter

Formatter.bold("kalın")            # *kalın*
Formatter.italic("italik")         # _italik_
Formatter.code("kod")              # `kod`
Formatter.user("U123456")          # <@U123456>
Formatter.channel("C123456")       # <#C123456>
Formatter.link("https://...", "tıkla")  # <https://...|tıkla>
Formatter.time(1234567890)         # <!date^1234567890^{date_num} {time}|...>
```

#### `MessageBuilder` — Fluent API

```python
from packages.slack.blocks.builder import MessageBuilder

blocks = (
    MessageBuilder()
    .add_header("Challenge Sonucu")
    .add_divider()
    .add_text("*Skor:* 8.5 / 10", fields=["*Takım:* <@U1> <@U2>", "*Süre:* 24 saat"])
    .add_button("GitHub'a Git", "open_github", url="https://github.com/...")
    .add_button("Kapat",       "close_btn",   style="danger")
    .add_context(["Değerlendirme tamamlandı"])
    .build()
)
```

> Arka arkaya eklenen butonlar aynı `actions` bloğuna eklenir (max 5).

#### `Layouts` — Hazır şablonlar

```python
from packages.slack.blocks.layouts import Layouts

# Hata mesajı
blocks = Layouts.error("Hata", "İşlem başarısız", details="ConnectionError: timeout")

# Başarı mesajı (buton opsiyonel)
blocks = Layouts.success("Tamamlandı", "Proje teslim edildi", "Detaylar", "view_details")

# Bilgi kartı
blocks = Layouts.info_card("Proje Bilgisi", "REST API challenge", icon="📋",
                            fields=["*Kategori:* Practice", "*Süre:* 24 saat"])
```

---

### Diğer Command Manager'lar

| Sınıf | İmport | Temel metodlar |
|-------|--------|----------------|
| `UserManager` | `packages.slack.commands.users` | `info(user)`, `list()`, `lookup_by_email(email)`, `profile_get(user)` |
| `ReactionManager` | `packages.slack.commands.reactions` | `add(channel, name, timestamp)`, `remove(name, channel, timestamp)`, `get(...)` |
| `PinManager` | `packages.slack.commands.pins` | `add(channel, timestamp)`, `remove(channel, timestamp)`, `list(channel)` |
| `FileManager` | `packages.slack.commands.files` | `upload(...)`, `delete(file)`, `info(file)`, `list()`, `get_upload_url_external(...)` |
| `CanvasManager` | `packages.slack.commands.canvases` | `create(title, content)`, `edit(canvas_id, changes)`, `delete(canvas_id)`, `access_set(...)` |
| `SearchManager` | `packages.slack.commands.search` | `messages(query)`, `files(query)`, `all(query)` |
| `UserGroupManager` | `packages.slack.commands.usergroups` | `create(name)`, `list()`, `update_users(usergroup, users)`, `enable(...)`, `disable(...)` |

Tüm manager'lar `WebClient` inject ederek oluşturulur:

```python
from packages.slack.commands.users import UserManager
users = UserManager(slack_client.bot_client)
info = users.info("U123456")
```

---

## SMTP

**Konum:** `packages/smtp/`

Opsiyonel e-posta bildirimleri. STARTTLS üzerinden thread-safe gönderim.

### Aktifleştirme

`.env` dosyasında her ikisi de dolu olmalıdır:

```env
SMTP_EMAIL=bot@example.com
SMTP_PASSWORD=app_password_here
```

`settings.smtp_enabled` bu iki alanın dolu olup olmadığını kontrol eder.

### Kullanım

```python
from packages.smtp.client import SmtpClient
from packages.smtp.schema import EmailMessage

client = SmtpClient()  # SMTP devre dışıysa RuntimeError fırlatır

# Ham HTML ile gönderim
client.send(EmailMessage(
    to=["admin@example.com"],
    subject="Challenge Tamamlandı",
    html="<h1>Tebrikler!</h1>",
    text_plain="Tebrikler!",
))

# Jinja2 şablonuyla gönderim
client.send_template(
    template_name="challenge_result",   # templates/challenge_result.html
    message=EmailMessage(
        to=["user@example.com"],
        cc=["admin@example.com"],
        subject="Değerlendirme Sonucu",
        body="Projeniz değerlendirildi.",
        template_vars={"score": 8.5, "team": ["Ahmet", "Ayşe"]},
    ),
)

# Kapanışta bağlantıyı kapat
SmtpClient.close_shared()
```

### `EmailMessage` Alanları

| Alan | Tip | Açıklama |
|------|-----|----------|
| `to` | `list[str]` | Alıcı adresleri (zorunlu) |
| `cc` | `list[str]` | CC adresleri |
| `bcc` | `list[str]` | BCC adresleri |
| `subject` | `str` | Konu (zorunlu) |
| `html` | `str \| None` | HTML gövde |
| `text_plain` | `str \| None` | Düz metin gövde |
| `body` | `str \| None` | Şablon bağlamına `body` / `message` olarak otomatik eklenir |
| `template_vars` | `dict` | Jinja2 şablonuna gönderilecek değişkenler |
| `reply_to` | `str \| None` | Reply-To başlığı |

> `html` veya `text_plain` alanlarından en az biri dolu olmalıdır.

---

## Settings

**Konum:** `packages/settings.py`

Pydantic tabanlı konfigürasyon. `.env` dosyasından otomatik okunur.

```python
from packages.settings import get_settings

s = get_settings()

print(s.slack_bot_token)
print(s.database)           # DB adı
print(s.smtp_enabled)       # bool — smtp_email ve smtp_password doluysa True
print(s.slack_admins)       # list[str] — virgülle ayrılmış ID'ler parse edilir
```

Tüm konfigürasyon alanları için bkz. [Challenge Servis Rehberi → Konfigürasyon](challenge-service.md#konfigürasyon).
