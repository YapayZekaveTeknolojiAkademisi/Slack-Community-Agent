# Changelog

Bu dosya [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) biçimine uyar ve [Semantic Versioning](https://semver.org/lang/tr/) ile uyumludur.

**Sürüm notu düzeni:** Her sürümde değişiklikler mümkün olduğunca **`packages/*`** (paylaşılan kütüphaneler) ve **`services/*`** (çalışan servisler) altında ayrılır; alt başlıklar ilgili modül veya dosya düzeyinde tutulur. `[Unreleased]` bölümünde yapılan işler birikir; sürüm etiketi kesildiğinde ilgili maddeler numaralı sürüm başlığının altına taşınır.

## [Unreleased]

Sonraki sürüme taşınacak değişiklikler. Eklerken mümkünse **`packages/...`** ve **`services/...`** alt başlıklarıyla hangi yapıyı etkilediğinizi belirtin.

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

---

## [2.0.1] - 2026-04-01

### Added

#### Migration sistemi (`migrations/`, `migrate.py`, `alembic.ini`)

- **`alembic.ini`:** Alembic konfigürasyon dosyası; `sqlalchemy.url` boş bırakıldı, URL `env.py` üzerinden çözümleniyor.
- **`migrate.py`:** Kullanımı kolay CLI aracı — `upgrade`, `downgrade`, `revision`, `autogenerate`, `current`, `history`, `heads`, `stamp`, `sql` komutlarını destekler.
- **`migrations/env.py`:** Async PostgreSQL desteğiyle Alembic ortamı; DB URL'sini `DATABASE_URL` → `get_settings()` → `POSTGRES_*` öncelik sırasıyla çözümler; `Base.metadata` üzerinden tüm modelleri otomatik yükler.
- **`migrations/versions/0001_initial_schema.py`:** Tüm 8 tabloyu ve `challengecategory` / `challengestatus` enum tiplerini oluşturan ilk migration.
- **`migrations/versions/0002_add_slack_id_to_members.py`:** `challenge_team_members` ve `challenge_jury_members` tablolarına `slack_id` kolonu ekler; mevcut `meta->>'slack_id'` verisini otomatik geri doldurur.

#### Dokümantasyon (`docs/`)

- **`docs/migration.md`:** Migration sistemi rehberi — tüm CLI komutları, tipik iş akışı, bağlantı konfigürasyonu, migration zinciri, autogenerate sınırları.
- **`docs/challenge-service.md`:** Challenge servis rehberi — slash komutları, tam yaşam döngüsü akışı, monitörler, değerlendirme kriterleri, kanal kayıt defteri, konfigürasyon tabloları, hata yönetimi.
- **`docs/packages.md`:** Paket kullanım rehberi — Logger, Database, Slack paketleri için ayrıntılı kullanım örnekleri; SMTP ve Settings için genel anlatım.

### Changed

#### `packages/database`

- **`mixins.py`:** `Base.metadata`'ya `naming_convention` eklendi; constraint isimleri artık tutarlı (`pk_`, `fk_`, `ix_`, `uq_`, `ck_` önekleri), autogenerate gürültüsü giderildi.

#### Dokümantasyon

- **`README.md`:** Dokümantasyon menüsüne `docs/packages.md` bağlantısı eklendi (3. madde).

### Fixed

#### `packages/database`

- **`manager.py`:** `initilaze` yazım hatası `initialize` olarak düzeltildi; `read_only` oturumda `SET TRANSACTION READ ONLY` düzgün uygulanmıyor, `text()` import'u eksik — her ikisi de giderildi; hata mesajları iyileştirildi.
- **`models/challenge.py`:** `ChallengeType.deadline_hours` tipi `Float` yerine `Integer` olarak düzeltildi; `ChallengeTeamMember` ve `ChallengeJuryMember` modellerine JSONB `meta` yerine doğrudan `slack_id: Mapped[str | None]` kolonu eklendi (indeksli).
- **`repository/challenge.py`:** `ChallengeTeamMember` ve `ChallengeJuryMember` için JSONB operatörü (`.meta.op("->>")(  "slack_id")`) kullanan tüm sorgular yeni `slack_id` kolonu ile değiştirildi.

#### `packages/settings`

- **`settings.py`:** `db_pool_pre_ping` ve `db_pool_recycle` alanları eksikti; `manager.py` bu alanlara eriştiği için uygulama `initialize()` sırasında `AttributeError` ile çöküyordu — her iki alan varsayılan değerleriyle eklendi.

#### `services/challenge_service`

- **`__main__.py`:** `db.initilaze()` çağrısı `db.initialize()` olarak düzeltildi.
- **`handlers/events/challenge.py`:** `ChallengeTeamMember` oluştururken `meta={"slack_id": slack_id}` yerine `slack_id=slack_id` kullanıldı.
- **`handlers/events/internal.py`:** `ChallengeJuryMember` oluştururken `meta={"slack_id": slack_id}` yerine `slack_id=slack_id` kullanıldı.
- **`handlers/events/evaluation.py`:** Tüm `(jm.meta or {}).get("slack_id")` erişimleri `jm.slack_id` ile değiştirildi.
- **`handlers/commands/evaluation.py`:** `jm` ve `tm` üzerindeki tüm `(*.meta or {}).get("slack_id")` erişimleri doğrudan `.slack_id` ile değiştirildi.
- **`core/queue/channel_registry.py`:** `_slack_ids_from_team()` ve `_slack_ids_from_jury()` fonksiyonları `meta` yerine `slack_id` kolonu kullanacak şekilde güncellendi.
- **`core/monitor/evaluation_monitor.py`:** Jüri mention'ları `(jm.meta or {}).get("slack_id")` yerine `jm.slack_id` ile oluşturulacak şekilde düzeltildi.

---

## [2.0.0] - 2026-03-31

İlk kayıtlı sürüm: mevcut kod tabanının paket ve servis bazında özetlenmesi.

### Added

#### `packages/settings`

- Tek modül (`settings.py`): **Pydantic Settings** ile ortam değişkeni yükleme (proje kökünde `.env`).
- **PostgreSQL:** `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`; bağlantı havuzu: `db_pool_size`, `db_max_overflow`, `db_pool_timeout`, `db_pool_pre_ping`, `db_pool_recycle`.
- **Slack:** `slack_bot_token`, `slack_user_token`, `slack_app_token`; kanal ve yönetici kimlikleri: `SLACK_WORKSPACE_OWNER_ID`, `SLACK_ADMIN_SLACK_ID`, `SLACK_ADMIN_CHANNEL`, `SLACK_CHALLENGE_CHANNEL`.
- **Monitör aralıkları (saniye):** `monitor_challenge_interval`, `monitor_deadline_interval`, `monitor_evaluation_interval`.
- **Challenge / değerlendirme:** `challenge_min_participants`, `challenge_max_participants`, `evaluation_max_wait_hours`, `evaluation_jury_count`.
- **SMTP (isteğe bağlı):** `smtp_host`, `smtp_port`, `smtp_timeout`, `smtp_email`, `smtp_password`; e-posta/şifre çift doğrulaması ve `smtp_enabled` özelliği.

#### `packages/database`

- **`manager.py`:** `DatabaseManager` — async SQLAlchemy engine ve `async_sessionmaker`; `initilaze` / `shutdown`; `session()` bağlam yöneticisi (`read_only` ile salt okunur oturum).
- **`models/base.py`:** SQLAlchemy bildirim tabanı (`Base`).
- **`models/mixins.py`:** Ortak mixin’ler (ör. kimlik ve zaman damgası).
- **`models/challenge.py`:** `ChallengeCategory`, `ChallengeStatus`, `ChallengeType`, `Challenge`, `ChallengeTeamMember`, `ChallengeJuryMember`.
- **`models/user.py`:** `User`, `UserRole`, `UserSession`.
- **`models/slack.py`:** `SlackUser`.
- **`repository/base.py`:** Repository temel kalıbı.
- **`repository/challenge.py`**, **`repository/user.py`**, **`repository/slack.py`:** İlgili varlıklar için veri erişim katmanı.

#### `packages/slack`

- **`client.py`:** Slack Bolt `App`, `WebClient` (bot ve user token), **Socket Mode** (`SocketModeHandler`) — tek giriş noktası `slack_client`.
- **`blocks/builder.py`**, **`blocks/layouts.py`:** Slack Block Kit bileşenleri ve düzen yardımcıları.
- **`commands/`:** Web API sarmalayıcıları — `chat`, `conversations`, `files`, `pins`, `reactions`, `search`, `usergroups`, `users`, `views`, `canvases`; `__init__.py` ile dışa aktarım.

#### `packages/logger`

- **`manager.py`:** Log kurulumu ve logger fabrikası (`get_logger`, `start_logging`).
- **`formatters.py`:** `SystemMessageFormatter`, `ErrorMessageFormatter`, `ApiMessageFormatter`, `QueueMessageFormatter`.
- **`filters.py`:** `SystemFilter`, `ErrorFilter`, `ApiFilter`, `QueueFilter` — kayıtları kanala göre ayırma.

#### `packages/smtp`

- **`client.py`:** E-posta gönderim istemcisi.
- **`template.py`**, **`schema.py`:** Şablon ve veri şeması.
- **`templates/welcome.html`:** Hoş geldin e-posta şablonu (HTML).

#### `services/challenge_service`

- **`__main__.py`:** Servis giriş noktası — arka plan `asyncio` döngüsü (`set_loop`), veritabanı başlatma, `service_manager.start()`, Slack Socket Mode’un bloklayıcı çalıştırılması, `SIGINT` / `SIGTERM` ile zarif kapanış; `--fresh` ile `StartupMode.FRESH`, aksi halde `RESUME`.
- **`manager.py`:** `ChallengeServiceManager` (tekil); `StartupMode` (`FRESH` / `RESUME`); başlangıçta DB temizliği, bellek sıfırlama, `ChannelRegistry` doldurma, monitörlerin başlatılması / durdurulması; iptal edilen challenge’lar için bildirim ve Slack kanal arşivleme akışı.
- **`logger.py`:** Servise özel `dictConfig` — dönen dosya handler’ları (`system`, `errors`, `api`, `queue`), stdout; log dizini `logs/challenge_service/`.
- **`core/event_loop.py`:** Bolt işleyicilerinden async iş çalıştırma (`run_async` vb.).
- **`core/queue/channel_registry.py`:** Kanal kayıt defteri ve başlangıçta DB’den yükleme (`_on_startup`).
- **`core/queue/challenge_queue.py`:** Kategori / jüri için `CustomQueue` ve kuyruk öğeleri.
- **`core/monitor/challenge_monitor.py`:** Challenge durumu için periyodik monitör.
- **`core/monitor/deadline_monitor.py`:** Son tarih monitörü.
- **`core/monitor/evaluation_monitor.py`:** Değerlendirme aşaması monitörü.
- **`handlers/commands/challenge.py`:** Challenge slash komutları ve ilgili iş akışı.
- **`handlers/commands/evaluation.py`:** Değerlendirme komutları.
- **`handlers/commands/internal.py`:** Dahili / yönetim komutları.
- **`handlers/commands/jury.py`:** `/jury` komutu (`join`, `leave`, `list` vb.).
- **`handlers/events/challenge.py`:** Challenge etkinlikleri (mesaj, etkileşim).
- **`handlers/events/evaluation.py`:** Değerlendirme etkinlikleri.
- **`handlers/events/internal.py`:** Dahili etkinlikler.
- **`handlers/__init__.py`:** Tüm handler modüllerinin içe aktarılması (dekoratör kayıtlarının yüklenmesi).
- **`utils/notifications.py`:** Başlangıç, kapanış ve iptal bildirimleri.
- **`utils/slack_helpers.py`:** Slack tarafı yardımcı işlemler (ör. kanal arşivleme).
- **`utils/slack_user_sync.py`:** Slack kullanıcı verisinin senkronu.
- **`utils/datetime_helpers.py`:** Tarih/saat yardımcıları.
- **`config/criteria.json`:** Değerlendirme ölçütleri yapılandırması.
- **`start.sh`**, **`stop.sh`:** Kabuk ile servisi başlatma / durdurma yardımcıları.

#### Dokümantasyon ve kök yapılandırma

- **`README.md`:** Paketler, servisler, özellikler, kapsam ve sürüm notları bağlantısı.
- **`CHANGELOG.md`:** Bu dosya — değişiklik geçmişi.
- **`.env.template`:** `Settings` ile uyumlu ortam değişkeni şablonu.
- **`requirements.txt`:** Python bağımlılık listesi (proje kökü).
