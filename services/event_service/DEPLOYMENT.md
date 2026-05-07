# Event Service — Yayina Alma Rehberi

## 1. Ortam Degiskenleri (.env)

### Zorunlu

```env
EVENT_CHANNEL=C...          # #serbest-kursu kanal ID'si
SLACK_ADMIN_CHANNEL=C...    # Admin bildirim kanal ID'si
SLACK_ADMINS=U...,U...      # Onay/red: yalnizca bu Slack user ID'leri moderator
```

Etkinlik onayı ve reddi (admin mesajındaki butonlar ve modal gönderimi) yalnızca `SLACK_ADMINS` listesindeki kullanıcılar tarafından tamamlanır; güncelleme ve iptal ile aynı yönetici kümesidir. Tek ID için `SLACK_ADMIN_SLACK_ID` de kabul edilir.

### Opsiyonel

```env
EVENT_REMINDER_ENABLED=true          # Hatirlatma sistemi (default: true)
EVENT_APPROVAL_TIMEOUT_HOURS=72      # Admin onay suresi — saat (default: 72)
EVENT_MAX_PENDING_PER_USER=0         # Bekleyen talep kotası / kullanıcı; 0=sinirsiz
```

### E-posta Bildirimleri Icin (Opsiyonel)

SMTP alanlari dolu degilse e-postalar sessizce atlanir, servis calismaya devam eder.

```env
SMTP_EMAIL=ornek@gmail.com
SMTP_PASSWORD=uygulama-sifresi
```

## 2. Veritabani

```bash
python migrate.py upgrade
```

Bu komut `events` ve `event_interest` tablolarini olusturur.

## 3. Slack App Konfigurasyonu

Slack App dashboard'unda `/event` slash komutunu ekleyin:
- Command: `/event`
- Short Description: Etkinlik yonetimi
- Usage Hint: `[create|list|my_list|history|add_me|update|cancel|help]`

Socket Mode aktif olmali (mevcut bot zaten kullaniyor).

## 4. Servisi Baslatma

Docker imajında varsayılan `CMD` compose ile aynıdır: **Socket yok** (`python -m services.event_service`). Yerel Socket için `python -m services.event_service --socket` veya compose `command` override.

```bash
# Bagimsiz calistirma (kendi Socket Mode baglantisi)
python -m services.event_service --socket

# Sadece handler + scheduler (Socket Mode baska process'te)
python -m services.event_service
```

## 5. Kontrol Listesi

- [ ] `.env` dosyasinda `EVENT_CHANNEL`, `SLACK_ADMIN_CHANNEL` ve `SLACK_ADMINS` dolu
- [ ] `python migrate.py upgrade` basariyla calistirildi
- [ ] Slack App'te `/event` komutu tanimli
- [ ] (Opsiyonel) SMTP alanlari dolu — e-posta bildirimleri icin
