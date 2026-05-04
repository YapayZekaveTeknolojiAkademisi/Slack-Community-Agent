# Dağıtım (deployment) rehberi

Bu proje **Docker Compose** ile birden fazla Python servisini ve **PostgreSQL (pgvector)** veritabanını birlikte çalıştırır. Üretim ortamı için de aynı kalıp kullanılabilir; aşağıdaki komutlar hem yerel hem sunucuda aynıdır (çalışma dizini: proje kökü).

## Ne nerede?

| Bileşen | Konum | Rol |
|--------|--------|-----|
| Orkestrasyon | `docker-compose.yml` | Servisler, ağ, volume’lar, profiller |
| Kolay komutlar | `Makefile` | `make up`, `make down`, migration, loglar |
| Ortam şablonu | `.env.template` → `.env` | Slack, Postgres, LLM anahtarları (`packages/settings.py` ile uyumlu) |
| Challenge + migrate imajı | `services/challenge_service/Dockerfile` | `challenge` + tek seferlik `migrate` job’ı |
| Event | `services/event_service/Dockerfile` | Zamanlayıcı; compose’ta `--socket` yok (Slack Socket challenge’da) |
| Feature request | `services/feature_request_service/Dockerfile` | Profil: `feature-standalone` |
| English | `services/english_service/Dockerfile` | Profil: `english-standalone` |
| Summary | `services/summary_service/Dockerfile` | Profil: `summary-standalone` |
| Veritabanı | `pgvector/pgvector:pg16-bookworm` | Volume: `pgdata` |
| Model önbelleği | — | Volume: `hf_cache` (Hugging Face vb.) |

**Varsayılan stack** (`docker compose up -d` / `make up`): `postgres` → `migrate` (Alembic `upgrade head`) → `challenge` + `event`.

## Önkoşullar

- Docker Engine + Docker Compose v2 (`docker compose`)
- Proje kökünde **`.env`**: `.env.template` kopyalanıp gerçek değerlerle doldurulmalı.

**Compose içinde Postgres:** `docker-compose.yml` içindeki `x-db-env` konteynerlara `POSTGRES_HOST=postgres` ve şifreyi verir. Yerel makinede `.env` içinde `POSTGRES_HOST=localhost` yazılı olsa bile compose bu değerleri **environment ile override** ettiği için konteynerler doğru host’a bağlanır. Şifre ve kullanıcı adı **hem** `postgres` servisinde **hem** uygulama servislerinde aynı olmalı (ör. `POSTGRES_PASSWORD` hem compose varsayılanı `postgres` ile hem `.env` ile uyumlu).

## Hızlı başlangıç

```bash
cp .env.template .env
# .env içini doldurun (Slack token’ları, GROQ, DB şifresi vb.)

make check          # docker / compose erişilebilir mi
make config         # compose şemasını doğrula
make up             # arka planda: postgres, migrate, challenge, event
make logs           # varsayılan: challenge
make logs S=event   # event logu
```

Güncel kodla imajları yeniden derleyerek kaldırmak:

```bash
make up-build
```

Durdurma:

```bash
make down           # volume’lar kalır (DB verisi kalır)
make down-v         # pgdata + hf_cache silinir — üretimde dikkat
```

## Makefile komutları (özet)

| Komut | Açıklama |
|--------|-----------|
| `make help` | Tüm hedefler ve kısa açıklamalar |
| `make check` | `docker` ve `compose` çalışıyor mu |
| `make config` | `docker compose config` (yapı doğrulama) |
| `make up` | Varsayılan stack, arka planda |
| `make up-build` | `--build` ile aynı |
| `make down` | Stack durur, volume’lar kalır |
| `make down-v` | Stack + volume’lar silinir |
| `make ps` | Konteyner durumu |
| `make build` / `make rebuild` | Sadece imaj derleme (`rebuild` = cache yok) |
| `make pull` | Taban imaj (postgres) çekme denemesi |
| `make logs` | `S=challenge\|event\|postgres\|migrate` (varsayılan: challenge) |
| `make logs-challenge` / `logs-event` / `logs-postgres` | Sabit servis logları |
| `make migrate` | Postgres ayaktayken Alembic `upgrade head` (`migrate` servisi) |
| `make shell-challenge` | `challenge` konteynerinde bash |
| `make up-feature` | `--profile feature-standalone` |
| `make up-english` | `--profile english-standalone` |
| `make up-summary` | `--profile summary-standalone` |

Makefile içinde `COMPOSE` değişkeni ile farklı bir compose binary’si kullanılabilir: `make up COMPOSE="docker compose"`.

## Docker Compose (doğrudan)

Makefile yoksa:

```bash
docker compose up -d
docker compose logs -f challenge
docker compose ps -a
docker compose down
```

Profilli servisler:

```bash
docker compose --profile feature-standalone up -d
docker compose --profile english-standalone up -d
docker compose --profile summary-standalone up -d
```

Sadece migration:

```bash
docker compose run --rm migrate
```

## Önemli: Slack Socket Mode

Aynı Slack **app** için **aynı anda yalnızca tek Socket Mode** süreci makuldür. Varsayılan stack’te Socket Mode **`challenge`** tarafında tutulur; `event` bileşeni compose’ta socket olmadan çalışır.

**`feature-request`**, **`english`**, **`summary`** her biri kendi profiliyle ayrı süreç olarak tanımlıdır; bunları **`challenge` ile aynı anda** aynı app token ile çalıştırmayın. İhtiyaca göre:

- Ya yalnızca varsayılan stack (`challenge` + `event`),
- Ya da **tek** ek Socket süreci için ilgili profili seçin (mimariyi buna göre tasarlayın; gerekirse ayrı Slack app veya HTTP modları).

## Veritabanı migrasyonları

- İlk açılışta `migrate` servisi `alembic upgrade head` çalıştırır; `challenge` ve `event` bunun **başarıyla bitmesine** bağlıdır.
- Çalışan bir ortamda şema güncellemek için: `make migrate` (veya `docker compose run --rm migrate`).

## Üretim notları (kısa)

- **Sırlar**: `.env` repoda tutulmamalı; sunucuda secrets manager veya güvenli env inject kullanın.
- **Yedekleme**: `pgdata` volume’u PostgreSQL verisini tutar; `down -v` kullanmadan önce yedek alın.
- **Gözlemlenebilirlik**: Loglar için `docker compose logs` veya merkezi log toplama entegrasyonu eklenebilir.
- **Tek makine dışı**: Aynı compose dosyası makine başına tek kopya gibi düşünülmüş; yüksek erişilebilirlik için DB ve servisleri ayrı orkestre etmek gerekir.

## Dosya referansları

- `docker-compose.yml` — servis tanımları ve `x-db-env`
- `Makefile` — günlük komutlar
- `.env.template` — zorunlu ve isteğe bağlı değişken listesi
