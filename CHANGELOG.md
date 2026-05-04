# Changelog

Bu dosya [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) biçimine uyar ve [Semantic Versioning](https://semver.org/lang/tr/) ile uyumludur.

**Sürüm notu düzeni:** Her sürümde değişiklikler mümkün olduğunca **`packages/*`** (paylaşılan kütüphaneler) ve **`services/*`** (çalışan servisler) altında ayrılır; alt başlıklar ilgili modül veya dosya düzeyinde tutulur. `[Unreleased]` bölümünde yapılan işler birikir; sürüm etiketi kesildiğinde ilgili maddeler numaralı sürüm başlığının altına taşınır.

## [Unreleased]

Sonraki sürüme taşınacak değişiklikler. Eklerken mümkünse **`packages/...`** ve **`services/...`** alt başlıklarıyla hangi yapıyı etkilediğinizi belirtin.

### Added

#### Dağıtım (Docker)

- **`docker-compose.yml`:** `postgres` (pgvector/pg16), tek seferlik **`migrate`** (`alembic upgrade head`), **`challenge`**, **`event`** (varsayılan CMD override ile Socket kapalı scheduler), `pgdata` ve `hf_cache` volume’ları; profilli ek süreçler: **`feature-request`** (`feature-standalone`), **`english`** (`english-standalone`), **`summary`** (`summary-standalone`) — aynı Slack app token ile birden fazla Socket Mode birlikte çalıştırılmamalı.
- **`.dockerignore`:** İmaj boyutunu düşürmek için `.venv`, `.git`, `logs` vb. hariç tutuldu.
- **`Makefile`:** `docker compose` kısayolları — `up` / `up-build`, `down` / `down-v`, `logs` (`S=` ile servis seçimi), `migrate`, `shell-challenge`, `up-feature` / `up-english` / `up-summary`, `check`, `config`, `build` / `rebuild`, `pull`, `ps`; `COMPOSE=` ile farklı compose binary’si.
- **`services/challenge_service/Dockerfile`**, **`services/event_service/Dockerfile`**, **`services/feature_request_service/Dockerfile`**, **`services/english_service/Dockerfile`**, **`services/summary_service/Dockerfile`:** Proje kökünden build; Python 3.12 slim, `libgomp1` / `build-essential`, ortak `requirements.txt` ve `PYTHONPATH=/app`; çalışma kullanıcısı `appuser` (uid 1000).

#### Dokümantasyon (kök)

- **`DEPLOYMENT.md`:** Compose tabanlı dağıtım rehberi — bileşen haritası, ortam / `x-db-env`, `make` ve doğrudan `docker compose` komutları, migrasyon, Socket Mode ve profil uyarıları, kısa üretim notları.

#### `services/challenge_service`

- **`api/state.py`**, **`api/__init__.py`:** 10 dakikalık teslimat penceresi için thread-safe bellek içi durum (`SubmissionWindowState` / `active_state`: `is_submission_open`, `set_submission_deadline`, `clear_submission_deadline`). Daha önce `handlers/commands/internal.py` ve `handlers/events/internal.py` `...api.state` modülüne referans veriyordu; dosya eksikliği import hatasına yol açıyordu.

#### `packages/settings`

- **Feature Request** yapılandırması: kota, rolling pencere günü, benzerlik / fraud eşikleri, `pending_bypass` temizlik saati, vektör idle aralığı, günlük embed-retry ve haftalık kümeleme / rapor zamanları (`event_timezone` ile uyumlu monitör yorumları için); `feature_request_similarity_exact >= feature_request_similarity_warning` doğrulaması.
- **`groq_model`:** Groq model adı (`GROQ_MODEL` / `groq_model`); servislerde LLM çağrılarında seçilebilir model.

#### `.env.template`

- `EVENT_CHANNEL`, LLM anahtarları (`GROQ_API_KEY`, `GEMINI_API_KEY`, `HF_TOKEN`), `GROQ_MODEL`, Feature Request ve Event opsiyonel env satırları genişletildi / hizalandı.

### Changed

#### `packages/database`

- **`repository/event.py`:** `list_current_month` ve `list_approved_for_interest_form` içinde “bugün” / pencere `get_settings().event_timezone` (`ZoneInfo`) ile yerel tarihe göre hesaplanıyor (yalnızca UTC kullanımı kaldırıldı).
- **`repository/feature_request.py`:** Haftalık / rolling pencere `feature_request_rolling_window_days` ve UTC `created_at` ile; fraud için `list_embedded_others_since`; `delete_stale_pending_bypass` kesimi `datetime.utcnow` yerine `timezone.utc` ile.

#### `services/event_service`

- **`core/scheduler.py`:** Modül ve bölüm yorumları sabit “72 saat” yerine `event_approval_timeout_hours` ile uyumlu olacak şekilde güncellendi.

#### `services/feature_request_service`

- **`service.py`:** Kota, benzerlik ve tutarlılık eşikleri, fraud penceresi ve rapor notları `get_settings()` üzerinden; `detect_fraud` rolling pencerede diğer kullanıcıların `embedded` kayıtlarıyla sınırlı; `cleanup_stale_pending_requests(None)` ayardaki saatleri kullanır; `retry_failed_embeddings` öncesi esnek `pending_bypass` temizliği.
- **`core/monitor/feature_monitor.py`:** Tüm zamanlamalar `get_settings()` alanlarından; günlük/haftalık tetikleyiciler `event_timezone` (`ZoneInfo`) ile yorumlanıyor.

#### `services/english_service`

- **`logger.py`:** `packages.logger` ile hizalama; **`llm/client.py`**, handler’lar, **`quiz_mode.py`**, **`writing_analyzer.py`** içinde `get_settings()` ve servis logger’ı (`_logger`) kullanımı.
- **`__main__.py`:** Logger kurulum sırası diğer import’lardan önce gelecek şekilde düzenlendi.

#### `services/summary_service`

- **`__main__.py`:** Logger import / başlatma sırası düzeltildi.
- **`core/summarizer.py`:** Özet modeli `settings.groq_model` (tanımsızsa `llama-3.1-8b-instant`).

### Deprecated

### Removed

### Fixed

#### `services/challenge_service`

- Eksik **`api.state`** modülü nedeniyle handler import zincirinin kırılması giderildi (`ModuleNotFoundError: services.challenge_service.api`).

#### `services/feature_request_service`

- Fraud skorunda docstring’te belirtilen “son N gün” ile uyum için DB tarafında tarih filtresi (`list_embedded_others_since`); önceden tüm `embedded` kayıtlar taranıyordu.

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
- **Slack:** `slack_bot_token`, `slack_user_token`, `slack_app_token`; kanal ve yönetici kimlikleri: `SLACK_WORKSPACE_OWNER_ID`, `SLACK_ADMINS` (virgülle çoklu; eski `SLACK_ADMIN_SLACK_ID` alias), `SLACK_ADMIN_CHANNEL`, `SLACK_CHALLENGE_CHANNEL`.
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
