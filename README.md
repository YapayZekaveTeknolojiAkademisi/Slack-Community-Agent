# Slack Community Agent

Slack topluluklarında **challenge tabanlı öğrenme süreçlerini** otomatize eden bot ailesi; aynı repoda etkinlik (`/event`), kanal özeti, özellik talebi ve diğer Socket tabanlı mikro-servisler bulunur.

---

## Dokümantasyon

| # | Döküman | Açıklama |
|---|---------|----------|
| 1 | [Migration Rehberi](docs/migration.md) | Veritabanı migration sistemi — kurulum, upgrade, downgrade, autogenerate |
| 2 | [Challenge Servis Rehberi](docs/challenge-service.md) | Slash komutları, iş akışları, monitörler, konfigürasyon |
| 3 | [Paket Kullanım Rehberi](docs/packages.md) | Logger, Database, Slack, SMTP ve Settings paketleri |
| 4 | [Event Servis Rehberi](docs/event-service.md) | `/event` akışı, scheduler, onay güvenliği, arka plan loop ve Slack I/O |
| 5 | [Summary Servis Rehberi](docs/summary-service.md) | `/channel-summary`, Groq özet akışı, chunker ve `[SUM]` admin logları |
| 6 | [Feature Request Servis Rehberi](docs/feature-request-service.md) | `/cemilimyapar`, kotalar, benzerlik akışı ve admin rapor komutları |

---

## Proje Yapısı

```
Slack Community Agent
├── packages/
│   ├── settings.py          Pydantic ayarları (.env okur)
│   ├── database/            PostgreSQL + SQLAlchemy async ORM + repository
│   ├── slack/               Slack Bolt + SDK istemcisi + Block Kit yardımcıları
│   ├── smtp/                E-posta bildirimleri (opsiyonel)
│   ├── logger/              Merkezi loglama
│   └── challenge_type_seeds.py  challenge_types seeds (servis açılışında DB ile senkron)
│
├── services/
│   ├── challenge_service/   Ana servis — kuyruk, challenge yaşam döngüsü, monitörler
│   ├── event_service/       Etkinlik talepleri, onay/red, zamanlayıcı hatırlatmalar
│   ├── summary_service/   /channel-summary — Groq ile kanal özeti
│   ├── feature_request_service/  Özellik talepleri (/cemilimyapar vb.)
│   └── english_service/     İngilizce pratik (ayrı Slack handler seti)
│
├── docs/                    Servis ve paket teknik rehberleri
├── seeds/                   challenge_types için JSON (dosya adı = kategori kökü; `id`: CHT-*; `points` elle)
├── migrations/              Alembic migration dosyaları
├── migrate.py               Migration CLI aracı
└── .env.template            Ortam değişkeni şablonu
```

---

## Hızlı Başlangıç

### Gereksinimler

- Python 3.12+
- PostgreSQL 14+
- Slack uygulaması (Bot Token, App Token, User Token)

### Kurulum

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Ortam Değişkenleri

```bash
cp .env.template .env
# .env dosyasını doldur
```

Zorunlu alanlar:

```env
# Veritabanı
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=slack_community_agent

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_USER_TOKEN=xoxp-...
SLACK_ADMINS=U0123456789
SLACK_COMMAND_CHANNELS=C0123456789
```

### Veritabanını Kur

```bash
python migrate.py upgrade
```

Challenge tipleri (`challenge_types`): **`python -m services.challenge_service` ile ilk DB oturumu açıldığında** `seeds/*.json` üzerinden senkronize edilir (`packages/challenge_type_seeds.py`). **`id`** `CHT-` ile başlamalı ve veritabanında aynı id varsa satır **atlanır**, yoksa **eklenir**. Her satırda şablon **`points`** JSON içinde **elle** yazılmalıdır (tamsayı; kategori bantları bu modülde tanımlı). `challenge_types.points` kolonu migrasyon `0005` ile eklenir.

Detaylar için → [Migration Rehberi](docs/migration.md)

### Servisi Başlat

```bash
# Normal başlatma — kaldığı yerden devam eder
python -m services.challenge_service

# Temiz başlatma — tüm challenge verisi sıfırlanır
python -m services.challenge_service --fresh
```

Diğer giriş noktaları: `python -m services.event_service` (`--socket` ile Socket), `python -m services.summary_service`, `python -m services.feature_request_service`, `python -m services.english_service`. Ayrıntılar için yukarıdaki `docs/` servis rehberleri.

---

## Teknoloji Yığını

| Katman | Teknoloji |
|--------|-----------|
| Bot framework | `slack_bolt` — Socket Mode |
| Veritabanı | PostgreSQL + `SQLAlchemy` 2.x async |
| Migration | `Alembic` |
| Konfigürasyon | `pydantic-settings` |
| E-posta | SMTP + Jinja2 (opsiyonel) |

---

## Değişiklik Geçmişi

[CHANGELOG.md](CHANGELOG.md)
