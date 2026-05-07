# Challenge Servis Rehberi

[← README](../README.md)

Slack üzerinden challenge yaşam döngüsünü yöneten ana servisin teknik dokümantasyonu.

---

## İçindekiler

- [Başlatma](#başlatma)
- [Slash Komutları](#slash-komutları)
- [Challenge Yaşam Döngüsü](#challenge-yaşam-döngüsü)
- [Kuyruk ve Eşleştirme](#kuyruk-ve-eşleştirme)
- [Monitörler](#monitörler)
- [Değerlendirme Kriterleri](#değerlendirme-kriterleri)
- [Kanal Registry](#kanal-registry)
- [Konfigürasyon](#konfigürasyon)
- [Hata Yönetimi](#hata-yönetimi)

---

## Başlatma

### Modlar

```bash
# Resume modu (varsayılan) — kaldığı yerden devam eder
python -m services.challenge_service

# Fresh modu — tüm challenge verisi sıfırlanır
python -m services.challenge_service --fresh
```

| Mod | Ne Temizlenir | Ne Korunur |
|-----|--------------|------------|
| **Resume** | `NOT_STARTED` challenge'lar | `STARTED`, `COMPLETED`, `IN_EVALUATION`, `EVALUATION_DELAYED`, `EVALUATED`, `NOT_COMPLETED` |
| **Fresh** | Tüm challenge, takım ve jüri verileri | `slack_users`, `challenge_types` |

### Başlatma Sırası

```
1. Background async event loop → ayrı thread
2. PostgreSQL bağlantısı (`db.initialize`)
3. challenge_types seed: `seeds/*.json` okunur; `CHT-*` id DB’de yoksa eklenir, varsa atlanır — `packages/challenge_type_seeds.py` (JSON hatası veya doğrulama hatasında servis başlamaz)
4. Slack Bolt handler'ların kayıt edilmesi (__main__.py import sırasında)
5. Service Manager başlatılır:
   a. DB temizliği (moda göre)
   b. ChannelRegistry rebuild (DB'den)
   c. Monitörler başlatılır
6. Startup bildirimleri Slack'e gönderilir
7. Slack Socket Mode başlar (blocking)
```

---

## Slash Komutları

### `/challenge` Komutları

Challenge kanalında çalışır (`SLACK_COMMAND_CHANNELS`). `submit` ve `evaluate` bu kuralın istisnasıdır.

---

#### `/challenge join`

Kategori seçim modalini açar ve katılımcıyı kuyruğa ekler.

**Akış:**
1. Kullanıcı kategori seçer (learn / practice / real_world / no_code_low_code)
2. Aktif challenge/kuyruk/beklemede kontrol edilir
3. Aynı kategoride bekleyen grup varsa → gruba katılır
4. Yoksa → ilgili kategori kuyruğuna eklenir

**Engeller:**
- Zaten kuyrukta, beklemede, aktif challenge veya değerlendirmede ise reddedilir

---

#### `/challenge start [n]`

`n` kişilik challenge başlatır (varsayılan: 2).

**Akış:**
1. Kullanıcı kategori ve takım büyüklüğü seçer
2. Kuyruktan `n-1` kişi çekilir
3. `n` kişiye ulaşıldıysa → challenge anında başlatılır
4. Ulaşılamadıysa → davet mesajı yayınlanır, 30 dk TTL ile beklemeye alınır

---

#### `/challenge leave`

Kuyruktan veya bekleyen gruptan ayrılır.

| Durum | Sonuç |
|-------|-------|
| Grup kurucusu ayrılırsa | Grup iptal edilir, diğerleri kuyruğa geri döner |
| Grup üyesi ayrılırsa | Davet mesajı güncellenir |
| Aktif challenge'daysa | Reddedilir |

---

#### `/challenge submit`

*(Sadece challenge kanalında)*

10 dakikalık teslim penceresi açar. GitHub URL ve proje açıklaması girilir.

**Güvenlik:**
- Pencerenin süresi dolmuşsa form reddedilir
- Eş zamanlı gönderim `SELECT FOR UPDATE` kilidiyle engellenir
- Teslim kaydedilince challenge kanalı arşivlenir, değerlendirme kanalı açılır

---

#### `/challenge evaluate`

*(Sadece değerlendirme kanalında, jüri üyelerine)*

4 soruluk puanlama formunu açar (bkz. [Değerlendirme Kriterleri](#değerlendirme-kriterleri)).

---

#### `/challenge list`

Kategorilere göre güncel kuyruk sayılarını gösterir (ephemeral).

---

#### `/challenge info`

Kullanıcının tüm challenge geçmişini kategorilere göre gösterir:
- Durum, proje adı, başlangıç/bitiş tarihleri, değerlendirme skoru, GitHub linki

---

#### `/challenge help`

Tüm komutları açıklamasıyla listeler.

---

### `/jury` Komutları

Herhangi bir kanalda çalışır.

---

#### `/jury join`

Kullanıcıyı jüri kuyruğuna ekler.

- Değerlendirme bekleyen challenge varsa → anında atanır
- Kullanıcı kendi takımının challenge'ını değerlendiremez (çakışma kontrolü)

#### `/jury leave`

Kullanıcıyı jüri kuyruğundan çıkarır.

#### `/jury list`

Jüri kuyruğundaki kullanıcıları sırayla listeler.

---

## Challenge Yaşam Döngüsü

### Durum Geçişleri

```
NOT_STARTED ──► STARTED ──► COMPLETED ──► IN_EVALUATION ──► EVALUATED
                   │                            │
                   ▼                            ▼
             NOT_COMPLETED              EVALUATION_DELAYED
                                               │
                                               ▼
                                         NOT_COMPLETED
```

| Durum | Açıklama |
|-------|----------|
| `NOT_STARTED` | Takım oluşuyor, henüz başlamadı |
| `STARTED` | Geliştirme süreci devam ediyor |
| `COMPLETED` | Teslim edildi, jüri atanmayı bekliyor |
| `IN_EVALUATION` | Jüri değerlendiriyor |
| `EVALUATED` | Tüm jüri tamamladı, skor belirlendi |
| `NOT_COMPLETED` | Süre doldu / teslim edilmedi / teslimden vazgeçildi |
| `EVALUATION_DELAYED` | Jüri değerlendirmesi zaman aşımına uğradı |

---

### Tam Akış

```
Kullanıcı /challenge join veya /challenge start N
         ↓
Kategori kuyruğu + eşleştirme
         ↓
Yeterli katılımcı ─────────────────────────────────────────────────────┐
         ↓                                                              │
Özel Slack kanalı oluşturulur (challenge-{kategori}-{uuid})           │
Takım üyeleri davet edilir                                             │
DB: Challenge (STARTED) + ChallengeTeamMember kayıtları               │
Hoş geldin mesajı: takım, proje, kontrol listesi, teslim talimatı     │
         ↓                                                              │
Geliştirme süreci (DeadlineMonitor izliyor)                           │
         ↓                                                              │
/challenge submit                                                      │
  → 10 dk pencere açılır                                              │
  → GitHub URL + açıklama formu                                       │
  → Teslim: Challenge COMPLETED                                        │
         ↓                                                             ◄┘
Değerlendirme kanalı oluşturulur (eval-{challenge_id})
Takım + admin davet edilir
Challenge kanalı arşivlenir
Jüri ataması denenir:
  Yeterli jüri varsa  → Jüri davet edilir, IN_EVALUATION
  Yoksa               → Duyuru yapılır, jüri beklenir
         ↓
/challenge evaluate (her jüri üyesi)
  → 4 soruluk form
  → Skor hesaplanır
  Son jüri tamamladığında:
    → Ortalama skor hesaplanır
    → EVALUATED
    → Değerlendirme kanalı arşivlenir
    → Sonuç duyurulur
```

---

## Kuyruk ve Eşleştirme

### Kuyruk Önceliklendirme

Kullanıcılar skor hesaplamasına göre sıraya girer:

```
skor = bekleme_süresi / (1.0 + denemeler × 0.5 × çarpan)
```

Tekrarlanan başarısız eşleşmeler bekleme süresini azaltır (öncelik düşer).

### Operasyonlar

| Operasyon | Açıklama |
|-----------|----------|
| `add()` | Kuyruğa ekle (tekrar engellidir) |
| `pop_n()` | En yüksek skorlu N kişiyi çek |
| `pop_n_excluding(ids)` | Belirtilen ID'leri atlayarak N kişiyi çek (jüri çakışması için) |
| `remove()` | Kuyruktan çıkar |
| `count()` | Kuyruk büyüklüğü |
| `is_in_queue()` | Üyelik kontrolü |

### Bekleyen Grup (Pending)

- Başlatıcı yeterli kişiyi çekemezse 30 dakika bekler
- Davet mesajı yayınlanır, katılan her üyeyle güncellenir
- 30 dk dolduğunda ChallengeMonitor grubu iptal eder ve üyeleri kuyruğa geri döndürür

---

## Monitörler

3 arka plan monitörü servis başlarken otomatik çalışır.

---

### ChallengeMonitor

**Varsayılan aralık:** 60 saniye (`MONITOR_CHALLENGE_INTERVAL`)

**Kanal Güvenliği:**
- Tüm aktif challenge ve değerlendirme kanallarının üyelerini kontrol eder
- Yetkisiz kullanıcılar (takım/jüri/admin/bot dışı) kanaldan çıkarılır

**Bekleyen Grup TTL:**
- 30 dakikayı geçen bekleyen gruplar iptal edilir
- Üyeler kuyruğa geri döner, bildirim gönderilir

---

### DeadlineMonitor

**Varsayılan aralık:** 300 saniye (`MONITOR_DEADLINE_INTERVAL`)

- `STARTED` durumdaki tüm challenge'ların süresini kontrol eder
- Süre hesabı: `challenge_started_at + deadline_hours + extended_hours`
- Süresi dolan challenge:
  - "Süre Doldu" mesajı yayınlanır
  - Challenge kanalı arşivlenir
  - Registry'den çıkarılır
  - `NOT_COMPLETED` olarak işaretlenir

---

### EvaluationMonitor

**Varsayılan aralık:** 600 saniye (`MONITOR_EVALUATION_INTERVAL`)

- `IN_EVALUATION` durumdaki challenge'ları izler

| Eşik | Eylem |
|------|-------|
| `evaluation_max_wait_hours` (varsayılan: 24 sa) | Jüri üyelerine hatırlatma mesajı gönderilir |
| `evaluation_max_wait_hours × 2` (varsayılan: 48 sa) | Değerlendirme zaman aşımı — kanal arşivlenir, `NOT_COMPLETED` |

---

## Değerlendirme Kriterleri

**Dosya:** `services/challenge_service/config/criteria.json`

| ID | Soru | Tip | Aralık |
|----|------|-----|--------|
| `q_working` | Proje çalışıyor mu / temel özellikler var mı? | boolean | Evet=10 / Hayır=0 |
| `q_clean_code` | Kod kalitesi ve yapısı | scale | 1–10 |
| `q_ux` | Kullanıcı deneyimi ve arayüz | scale | 1–10 |
| `q_innovative` | Yaratıcılık ve yenilik | scale | 1–10 |

**Nihai skor** = tüm kriterlerin aritmetik ortalaması

---

## Kanal Registry

`ChannelRegistry` — servis hafızasında aktif kanalları tutar. PostgreSQL değildir; servis yeniden başladığında DB'den yeniden kurulur.

### ChannelRecord

| Alan | Açıklama |
|------|----------|
| `channel_id` | Slack kanal ID'si |
| `challenge_id` | DB Challenge ID'si |
| `members` | Takım üyelerinin Slack ID listesi |
| `jury` | Jüri üyelerinin Slack ID listesi |
| `admin_slack_id` | Admin Slack ID'si |

### Kayıt Türleri

- **Challenge kanalları** — yalnızca `STARTED` (aktif takım Slack kanalı; `challenge_channel_id` dolu olanlar). `COMPLETED` sonrası bu kanal arşivlenir ve kayıtta tutulmaz.
- **Değerlendirme kanalları** — `evaluation_channel_id` dolu olduğu sürece: teslim sonrası jüri bekleyen `COMPLETED`, ayrıca `IN_EVALUATION` ve `EVALUATION_DELAYED`. Takım üye listesi için DB kullanılır; teslim sırasında `challenge_channel_id` DB'de sıfırlanır ve registry'de pch kaldırılır.

Teslim sırasında değerlendirme kaydı oluşturulur (`register_evaluation`, jüri listesi başta boş). Jüri atanınca aynı kayıt güncellenir (`set_evaluation_jury`).

### Kullanıcı bağlılığı (`is_user_engaged`)

**Dosya:** `services/challenge_service/manager.py` (registry kısmı: `services/challenge_service/core/engagement.py` içindeki `engaged_from_registry_channel_views`)

`/challenge join`, `/challenge start` ve modal akışları kullanıcının zaten meşgul olup olmadığını buradan sorar. Kontrol sırası:

1. Kategori kuyrukları (`CustomQueue`)
2. Pending grup (bekleyen eşleşme)
3. Challenge registry — `members` içinde Slack ID (yalnızca `STARTED` takım kanalı)
4. Evaluation registry — `members` içinde Slack ID (teslim sonrası + aktif değerlendirme; jüri beklerken dahil), veya `jury` içinde Slack ID

`COMPLETED` + jüri bekliyor durumunda takım yalnızca değerlendirme kaydında tutulduğundan, yeni challenge’a izin verilmez ve `/challenge leave` bu durumda kuyruk çıkışı için geçerli değildir (kullanıcıya ayrı ephemeral metin gösterilir).

---

## Konfigürasyon

**Dosya:** `packages/settings.py`

### Slack

| Değişken | Açıklama | Zorunlu |
|----------|----------|---------|
| `SLACK_BOT_TOKEN` | Bot token (`xoxb-...`) | Evet |
| `SLACK_APP_TOKEN` | Socket Mode token (`xapp-...`) | Evet |
| `SLACK_USER_TOKEN` | Kullanıcı token — kanal oluşturma için (`xoxp-...`) | Evet |
| `SLACK_ADMINS` | Virgülle ayrılmış admin Slack ID listesi | Evet |
| `SLACK_COMMAND_CHANNELS` | Virgülle ayrılmış komut kanalı ID listesi | Hayır |
| `SLACK_CHALLENGE_CHANNEL` | Challenge komutlarının ana topluluk kanalı (`C...`) | Evet |
| `SLACK_ADMIN_CHANNEL` | Operasyon günlüğü (emoji yok, kısaltmalı `[CHG]` satırları) | Evet |
| `SLACK_ANNOUNCEMENT_CHANNEL` | Yeni challenge uzun duyurusu; boşsa `SLACK_CHALLENGE_CHANNEL` | Hayır |
| `SLACK_STARTUP_CHANNEL` | Başlangıç bildirim kanalı | Hayır |
| `SLACK_REPORT_CHANNEL` | Rapor kanalı | Hayır |

**Bildirim ayrımı**

- **Admin kanalı** (`SLACK_ADMIN_CHANNEL`): challenge başlangıcı, teslim sonrası eval açılışı, süre dolumu / bırakma, jüri tamamı, servis açılış/kapanış. Satırlar `[CHG] ETİKET| ...` biçiminde; emoji yok; kısaltmalar: `EVT` olay, `YAP` yapıldı, `SRB` sıradaki adım, `KT` katılımcılar, `RSN` neden (`surrender` / `deadline`).
- **Topluluk duyuru**: yeni challenge başladığında Block Kit ile uzun açıklama `SLACK_ANNOUNCEMENT_CHANNEL` doluysa oraya, değilse `SLACK_CHALLENGE_CHANNEL` kanalına gider (emoji serbest). Özel challenge kanalındaki karşılama mesajı ayrıca kalır.

### Veritabanı

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `POSTGRES_USER` | — | Kullanıcı adı |
| `POSTGRES_PASSWORD` | — | Şifre |
| `POSTGRES_HOST` | `localhost` | Host |
| `POSTGRES_PORT` | `5432` | Port |
| `POSTGRES_DB` | — | Veritabanı adı |
| `DB_POOL_SIZE` | `5` | Bağlantı havuzu boyutu |
| `DB_MAX_OVERFLOW` | `10` | Ek bağlantı sayısı |
| `DB_POOL_TIMEOUT` | `30` | Havuz bekleme süresi (sn) |
| `DB_POOL_PRE_PING` | `true` | Bağlantı canlılık kontrolü |
| `DB_POOL_RECYCLE` | `3600` | Bağlantı yenileme süresi (sn) |

### Monitörler

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `MONITOR_CHALLENGE_INTERVAL` | `60` | Kanal güvenlik + TTL kontrolü (sn) |
| `MONITOR_DEADLINE_INTERVAL` | `300` | Süre bitiş kontrolü (sn) |
| `MONITOR_EVALUATION_INTERVAL` | `600` | Jüri zaman aşımı kontrolü (sn) |

### Challenge Limitleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `EVALUATION_MAX_WAIT_HOURS` | `24` | Hatırlatma eşiği; 2 katı zaman aşımı eşiği |
| `EVALUATION_JURY_COUNT` | `2` | Jüri paneli büyüklüğü |

### SMTP (Opsiyonel)

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SMTP_EMAIL` | — | Gönderen adres |
| `SMTP_PASSWORD` | — | Şifre |
| `SMTP_HOST` | `smtp.gmail.com` | Sunucu |
| `SMTP_PORT` | `587` | Port (STARTTLS) |
| `SMTP_TIMEOUT` | `10` | Zaman aşımı (sn) |
| `ADMIN_EMAIL` | — | Virgülle ayrılmış alıcı adresleri |

> SMTP etkinleştirmek için `SMTP_EMAIL` ve `SMTP_PASSWORD` ikisi birden dolu olmalıdır.

---

## Hata Yönetimi

### Eş Zamanlılık Kilitleri

| Senaryo | Koruma |
|---------|--------|
| Aynı anda iki teslim | `SELECT FOR UPDATE` kilidi |
| Aynı anda iki jüri puanlaması | `SELECT FOR UPDATE` kilidi |
| Kuyruk pop + katılım yarışı | `pending_lock` ile atomik kontrol |

### En İyi Çaba (Best-Effort) Deseni

Servis kritik olmayan hatalarda durmaz:

| Hata | Davranış |
|------|----------|
| Kanal oluşturma başarısız | Katılımcılar kuyruğa geri döner |
| Jüri ataması başarısız | Jüri üyeleri kuyruğa geri döner, challenge `COMPLETED` kalır |
| Kanal arşivleme başarısız | Uyarı loglanır, süreç devam eder |
| Slack API geçici hatası | Loglanır, bir sonraki döngüde tekrar denenir |

### Resume Modunda Kurtarma

Servis yeniden başladığında:
- `STARTED` / `COMPLETED` challenge kanalları registry'e eklenir
- `IN_EVALUATION` / `EVALUATION_DELAYED` değerlendirme kanalları registry'e eklenir
- Monitörler kaldıkları yerden devam eder
- `NOT_STARTED` challenge'lar temizlenir (takım oluşumu tamamlanamamış)
