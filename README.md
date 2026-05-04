# Slack Community Agent

Slack topluluklarında **challenge tabanlı öğrenme süreçlerini** otomatize eden bot servisi. Takım oluşturma, proje atama, teslim alma ve jüri değerlendirmesinden oluşan tam yaşam döngüsünü yönetir.

---

## Dokümantasyon

| # | Döküman | Açıklama |
|---|---------|----------|
| 1 | [Migration Rehberi](docs/migration.md) | Veritabanı migration sistemi — kurulum, upgrade, downgrade, autogenerate |
| 2 | [Challenge Servis Rehberi](docs/challenge-service.md) | Slash komutları, iş akışları, monitörler, konfigürasyon |
| 3 | [Paket Kullanım Rehberi](docs/packages.md) | Logger, Database, Slack, SMTP ve Settings paketleri |

---

## Proje Yapısı

```
Slack Community Agent
├── packages/
│   ├── settings.py          Pydantic ayarları (.env okur)
│   ├── database/            PostgreSQL + SQLAlchemy async ORM + repository
│   ├── slack/               Slack Bolt + SDK istemcisi + Block Kit yardımcıları
│   ├── smtp/                E-posta bildirimleri (opsiyonel)
│   └── logger/              Merkezi loglama
│
├── services/
│   └── challenge_service/   Ana servis
│       ├── handlers/        Slash komut ve event handler'ları
│       ├── core/            Kuyruk, registry, monitörler
│       └── config/          Değerlendirme kriterleri (criteria.json)
│
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

Detaylar için → [Migration Rehberi](docs/migration.md)

### Servisi Başlat

```bash
# Normal başlatma — kaldığı yerden devam eder
python -m services.challenge_service

# Temiz başlatma — tüm challenge verisi sıfırlanır
python -m services.challenge_service --fresh
```

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
