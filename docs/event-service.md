# Event Servis Rehberi

[← README](../README.md)

Topluluk etkinliklerini Slack üzerinden talep, onay, duyuru ve hatırlatma ile yöneten servisin teknik özeti. Operasyonel yayın adımları için ayrıca [Event Service — Yayına Alma Rehberi](../services/event_service/DEPLOYMENT.md) kaydına bakın.

---

## İçindekiler

- [Başlatma](#başlatma)
- [Arka plan asyncio ve Slack I/O](#arka-plan-asyncio-ve-slack-io)
- [Zamanlayıcı (scheduler)](#zamanlayıcı-scheduler)
- [Slash komutları `/event`](#slash-komutları-event)
- [Modallar, butonlar ve yetkiler](#modallar-butonlar-ve-yetkiler)
- [Konfigürasyon özeti](#konfigürasyon-özeti)
- [Kod düzeni](#kod-düzeni)

---

## Başlatma

Servis iki süreç modelini destekler: aynı süreçte hem Socket Mode hem DB + zamanlayıcı, ya da yalnızca arka plan bileşenleri (Socket başka süreçte).

```bash
# Socket Mode bu süreçte (tipik yerel / tek konteyner senaryosu)
python -m services.event_service --socket

# Yalnızca handler import + DB + scheduler (Socket başka worker’da)
python -m services.event_service
```

Özet başlatma sırası (`__main__.py`):

```
1. Arka plan asyncio event loop → ayrı thread + set_loop()
2. db.initialize() ve event_scheduler.start()
3. Sinyal işleyicileri (SIGINT/SIGTERM) → kapanış Future’ı planla
4. --socket ise Slack connect() + ana thread stop.wait()
5. Kapanışta _shutdown() beklenir → socket kapatılır → loop durur
```

Socket yaşam döngüsü (`connect` / `close`, `start()` sonsuz beklemesi yok) **challenge** ve **summary** ile hizalıdır: `packages.slack.socket_runtime`.

---

## Arka plan asyncio ve Slack I/O

- **Bolt handler’ları** ayrı iş parçacıklarında çalışır; veritabanı erişimi **`run_async(coro)`** ile arka plan döngüsüne **`run_coroutine_threadsafe`** ile yönlendirilir (`services/event_service/core/event_loop.py`). Böylece asyncpg havuzu tek loop’a bağlı kalır; “wrong loop” hataları önlenir.

- **Senkron Slack WebClient** çağrıları (ör. `chat_postMessage`, `conversations.info`, `users.info`) arka plan döngüsünün üzerinde blokaj yaratmaması için Bolt tarafında **`run_slack_io(callable)`** kullanılır (`services/event_service/utils/slack_io.py` → `asyncio.to_thread`). Zamanlayıcı içinde benzer amaç için doğrudan **`await asyncio.to_thread(...)`** kullanılır (`core/scheduler.py`).

---

## Zamanlayıcı (scheduler)

`EventScheduler` yaklaşık 60 saniyede bir döner (`core/scheduler.py`):

| Görev | Davranış |
|-------|----------|
| **Onay zaman aşımı** | `PENDING` kayıtlar `EVENT_APPROVAL_TIMEOUT_HOURS` üzeri beklediyse reddedilir; kullanıcıya DM/e-posta ve admin mesajı güncellemesi Slack ve e-posta ile yapılır (`to_thread` ile I/O). |
| **COMPLETED geçişi** | Tarihi geçmiş `APPROVED` etkinlikler `COMPLETED` olur. |
| **Gün başı hatırlatma** | Yerel TZ’de ayarlanan saatte (`event_morning_reminder_hour`) bugünkü onaylı etkinlikler duyuru kanallarında özetlenir; ilgi gösterenlere e-posta gönderilebilir (`EVENT_REMINDER_ENABLED`). |
| **10 dk öncesi** | Etkinlikten 9–11 dakika önce ilgili kullanıcılara duyuru ve e-posta (meta ile tekrar gönderim engellenir). |

---

## Slash komutları `/event`

Komutların çalışma kanalı: `SLACK_ANNOUNCEMENT_CHANNEL` doluysa **yalnızca** o kanal; boşsa `EVENT_CHANNEL`.

| Alt komut | Kısa açıklama |
|-----------|----------------|
| **`create`** | Etkinlik oluşturma modalı (`PENDING` talep → admin bildirimi). |
| **`list`** | Bu ayın onaylı etkinlikleri ve ilgi sayıları. |
| **`my_list`** | Kullanıcının oluşturduğu etkinlikler (durum ile). |
| **`history`** | Tamamlanan / iptal edilmiş geçmiş. |
| **`add_me`** | İlgi gösterme modalı (önümüzdeki N gün). |
| **`update`** | Onaylı etkinlik güncelleme (iki adımlı modal). |
| **`cancel`** | Onaylı etkinlik iptal modalı. |
| **`help`** | Ephemeral özet yardım (`EVENT_MAX_PENDING_PER_USER` &gt; 0 ise kota notu). |

---

## Modallar, butonlar ve yetkiler

- **Admin talep iletisi**: `post_admin_request` ile `SLACK_ADMIN_CHANNEL`’a “Onayla / Reddet” butonları gider (`notifications.py`).

- **Onay / red** (`event_approve_btn`, `event_reject_btn` ve modal `event_admin_approve_modal` / `event_admin_reject_modal`):
  - Yalnızca **`SLACK_ADMINS`** içindeki Slack user ID’leri işlemi tamamlayabilir; aksi kullanıcıya ephemeral/DM ile bilgi verilir ve veritabanı değişmez.

- **Bekleyen talep kotası**: `EVENT_MAX_PENDING_PER_USER` &gt; 0 ise kullanıcı başına eşzamanlı `PENDING` sayısı sınırlıdır (`packages/database/repository/event.py` → `count_pending_by_creator`); hem `/event create` öncesi hem modal gönderiminde kontrol vardır.

- **İlgi**: `event_interest_btn`, `event_add_me_modal`, Google Takvim linki `_calendar_url` ile (Slack kanalı lokasyonunda `conversations.info` tetiklenebilir — `run_slack_io` ile sarılı).

---

## Konfigürasyon özeti

Ortam değişkenlerinin tam listesi ve yayın checklist’i: [DEPLOYMENT.md](../services/event_service/DEPLOYMENT.md).

Çekirdek alanlar: `EVENT_CHANNEL`, `SLACK_ADMIN_CHANNEL`, `SLACK_ADMINS`, `EVENT_APPROVAL_TIMEOUT_HOURS`, `EVENT_MAX_PENDING_PER_USER`, `EVENT_REMINDER_ENABLED`, `EVENT_TIMEZONE`, `SLACK_ANNOUNCEMENT_CHANNEL` (opsiyonel), SMTP alanları (opsiyonel e-posta).

---

## Kod düzeni

```
services/event_service/
├── __main__.py              Giriş, loop, scheduler, (--socket)
├── core/
│   ├── event_loop.py        run_async / get_loop
│   └── scheduler.py         Periyodik görevler
├── handlers/
│   ├── commands/event.py    /event router, modaller
│   └── events/event.py      View + block action işleyicileri
├── utils/
│   ├── notifications.py     Duyuru, DM, admin mesajları
│   ├── slack_io.py          run_slack_io (Bolt → to_thread)
│   └── slack_profiles.py    Toplu kullanıcı adı çözümü (users.info)
└── DEPLOYMENT.md           Operasyon rehberi
```
