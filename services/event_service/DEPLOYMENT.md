# Event Service — Yayina Alma Rehberi

## 1. Ortam Degiskenleri (.env)

### Zorunlu

```env
EVENT_CHANNEL=C...          # #serbest-kursu kanal ID'si
SLACK_ADMIN_CHANNEL=C...    # Admin bildirim kanal ID'si
```

### Opsiyonel

```env
EVENT_REMINDER_ENABLED=true          # Hatirlatma sistemi (default: true)
EVENT_APPROVAL_TIMEOUT_HOURS=72      # Admin onay suresi — saat (default: 72)
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

```bash
# Bagimsiz calistirma (kendi Socket Mode baglantisi)
python -m services.event_service --socket

# Sadece handler + scheduler (Socket Mode baska process'te)
python -m services.event_service
```

## 5. Kontrol Listesi

- [ ] `.env` dosyasinda `EVENT_CHANNEL` ve `SLACK_ADMIN_CHANNEL` dolu
- [ ] `python migrate.py upgrade` basariyla calistirildi
- [ ] Slack App'te `/event` komutu tanimli
- [ ] (Opsiyonel) SMTP alanlari dolu — e-posta bildirimleri icin
