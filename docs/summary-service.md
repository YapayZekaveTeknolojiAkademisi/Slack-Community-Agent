# Summary Servis Rehberi

[← README](../README.md)

Slack kanallarındaki son mesajları toplayıp Groq LLM ile özetleyen servisin teknik özeti. Kullanıcıya sonuç **yalnızca ephemeral** (kanalı kirletmez); admin kanalına kısa denetim satırları düşebilir.

---

## İçindekiler

- [Başlatma](#başlatma)
- [Komutlar ve akış](#komutlar-ve-akış)
- [Özet üretimi (fetch → chunk → summarize)](#özet-üretimi-fetch--chunk--summarize)
- [Admin bildirimleri](#admin-bildirimleri)
- [Konfigürasyon](#konfigürasyon)
- [Kod düzeni](#kod-düzeni)

---

## Başlatma

```bash
python -m services.summary_service
```

Başlatma sırası (`__main__.py`):

```
1. Logger
2. Sinyal işleyici (SIGINT/SIGTERM) → stop olayı (install_stop_signals)
3. Bolt handler kayıtları (import services.summary_service.handlers)
4. Slack Socket Mode connect(); ana thread stop.wait()
5. Kapanışta socket_handler.close()
```

Özet:

- Serviste **PostgreSQL veya arka plan asyncio worker** yok; iş yükü senkron/Blok Slack + HTTP (Groq) çağrılarıdır.
- Socket yaşam döngüsü **challenge/event** ile aynı **`packages.slack.socket_runtime`** kalıbıdır.

---

## Komutlar ve akış

### `/channel-summary`

| Kullanım | Sonuç |
|----------|--------|
| *(parametresiz)* | Bulunulan kanal için zaman penceresi (varsayılan 24 saat) + **kısa / detaylı** mod seçim butonları (ephemeral). |
| **`/channel-summary <1–168>`** | Saat aralığını değiştirip aynı mod paneli. |
| **`/channel-summary all`** | Kullanıcının üye olduğu tüm kanallar için rollup özet; yine mod seçimi (daha sıkı thread/limit). |
| **`/channel-summary help`** | Ephemeral yardım (Türkçe). |

### `/summary`

Workspace’e kısayol olarak eklendiyse **yalnızca yardım** veya “asıl komut `/channel-summary`” uyarısı (`handlers/commands/summary.py`).

### Block actions

- **`summary_brief`** / **`summary_detailed`**: Tek kanal özetini başlatır (meta JSON: `channel_id`, `hours`, `user_id`).
- **`summary_brief_all`** / **`summary_detailed_all`**: Tüm kanallar rollup akışı.

Akış içi kullanıcı geri bildirimi: önce “hazırlanıyor” ephemeral’ı; hata/boş/yoğunluk durumlarında bloklu veya kısa metin ephemeral’ları (`format_*` yardımcıları).

---

## Özet üretimi (fetch → chunk → summarize)

1. **`message_fetcher`**: Slack API ile kanal geçmişi + thread yapısı (zorunlu kapsamlar: kanal/geçmiş; bot kanal üyesi olmalıdır).

2. **`chunker`**: Metinleri model bağlamına göre parçalar; tek bir çok uzun satır bağlamı aşarsa **kırpılır**, ayrı birden fazla chunk’a **bölünmez** (token bütçesine sığdırma).

3. **`summarizer`**: Groq üzerinden map-reduce benzeri özet; **`GROQ_API_KEY`** yoksa kullanıcıya yapılandırma hatası gösterilir (`is_summarizer_configured`).

Kişisel bölüm: kullanıcı mention’ları ve thread yanıtları `filter_personal_messages` ile ayrılıp mümkünse `summarize_personal` ile ek özet üretilir.

Groq tarafında geçici yoğunluk / kota benzeri hatalarda kullanıcıya “bir süre sonra tekrar deneyin” mesajları (`summarizer_exc_is_transient_overload`) üretilir.

---

## Admin bildirimleri

`SLACK_ADMIN_CHANNEL` doluysa özet işi başladığında ve bittiğinde kısa log satırları gönderilir (`utils/notifications.py`):

- **`[SUM]`** öneki (`packages/slack/service_prefixes.py` → `PREFIX_SUMMARY`), challenge ile aynı sade görünüm fikrine uygun.
- Alanlar arasında kısaltılmış etiketler (örn. kullanıcı, kapsam, saat, mod, başarı/hata kodu).

---

## Konfigürasyon

| Alan (env önceliği sistemde tanımlı) | Rol |
|-------------------------------------|-----|
| **`GROQ_API_KEY`** | Özet için zorunlu. |
| **`GROQ_MODEL`** | Opsiyonel model seçimi. |
| **`SUMMARY_MAX_THREADS_PER_CHANNEL`** | Tek kanal: thread başlığı üst sınırı (0=kapalı). |
| **`SUMMARY_MAX_REPLIES_PER_THREAD`** | Thread başına yanıt satırı üst sınırı. |
| **`SUMMARY_MAX_THREADS_ALL`** / **`SUMMARY_MAX_REPLIES_PER_THREAD_ALL`** | `/channel-summary all` için daha sıkı limitler. |
| **`SUMMARY_MIN_WORDS_PER_MESSAGE`** | Çok kısa mesajları LLM’e göndermeme eşiği. |
| **`SUMMARY_ATTRIBUTION_LABEL`** | Özet sonunda atıf metni. |
| **`SLACK_ADMIN_CHANNEL`** | Opsiyonel admin log kanalı. |

Tam alan listesi: `packages/settings.py` içinde `summary_*` ve `groq_*` alanları.

---

## Kod düzeni

```
services/summary_service/
├── __main__.py              Socket + sinyal
├── handlers/commands/
│   └── summary.py           /channel-summary, /summary, block actions
├── core/
│   ├── message_fetcher.py   Slack'ten mesaj + thread toplama
│   ├── chunker.py           Token bütçesine göre parçalama
│   └── summarizer.py        Groq çağrıları, yoğunluk tespiti
├── utils/
│   ├── formatters.py        Block Kit çıktıları
│   └── notifications.py     [SUM] admin satırları
└── Dockerfile
```
