# Feature Request Servis Rehberi

[← README](../README.md)

Topluluktan gelen ürün/özellik taleplerini toplayan, organize eden ve bildiren ana servisin teknik dokümantasyonu.

---

## İçindekiler

- [Başlatma](#başlatma)
- [Komutlar ve İşleyiciler](#komutlar-ve-i̇şleyiciler)
- [Monitörler](#monitörler)

---

## Başlatma

### Komut

Servis standart olarak aşağıdaki komut ile başlatılabilir:

```bash
python -m services.feature_request_service
```

### Başlatma Sırası

```
1. Arka plan async event loop'u yapılandırılır ve başlatılır (ayrı bir thread üzerinde).
2. Veritabanı bağlantısı (`db.initialize()`) kurulur.
3. Servis Yöneticisi (`service_manager`) başlatılır.
4. Sinyal (SIGINT, SIGTERM) işleyicileri kurulur.
5. Slack Socket Mode başlatılır.
```

---

## Komutlar ve İşleyiciler

Bu servis, özelliğe/talebe yönelik Slack üzerinden gelen etkileşimleri slash komutları, modal (*view submission*) gönderimleri ve buton (*block action*) tıklamaları ile işler. Özel olarak geliştirilmiş semantik benzerlik algoritmaları ve aylık kotalar etrafında şekillenir.

### Slash Komutları

- **`/cemilimyapar`**
  Kullanıcıların yeni bir ürün özelliği veya geliştirme fikri sunabilmesi için `feature_request_modal` ekranını (arayüzünü) açar.
- **`/cemil-report feature-requests`**
  Admine özel raporlama komutudur. Çalıştırıldığında arka planda `run_clustering_pipeline(is_preview=True)` tetiklenerek bekleyen talepler (AI/LLM desteği ile) kümelenir ve kanal/kullanıcı bazlı detaylı bir admin önizleme raporu (`Layouts.feature_request_report`) DM üzerinden sunulur. Yalnızca `slack_admins` yapılandırmasındaki kullanıcılar çalıştırabilir.
- **`/cemil-report cluster-details <id>`**
  Spesifik bir "cluster" (küme) detayını incelemek isteyen yöneticiler için geliştirilmiştir. İlgili cluster içerisindeki tüm özellik talebi detaylarını (`Layouts.feature_cluster_details`) listeler. Yalnızca adminler kullanabilir.

### Modallar (View Submissions)

- **`feature_request_modal`** 
  Kullanıcı `/cemilimyapar` pop-up'ını doldurup gönderdiğinde devreye girer. Dört temel durumu yönetir:
  1. **created**: Talep yeniyse başarıyla veritabanına kaydedilir.
  2. **similar_found**: Gönderilen metin vektörel/anlamsal olarak öncekilerle benzerlik gösteriyorsa kullanıcı uyarılır. Talep "beklemede" (pending) kalır ve kullanıcıya "Mevcut olanı düzenle", "Yine de yeni olarak kaydet" veya "İptal et" seçenekleri sunulur.
  3. **exact_match**: Büyük oranda birebir eşleşen çok benzer bir talep varsa doğrudan reddedilir ve mevcut talebi düzenlemesi istenir.
  4. **quota_exceeded**: Kullanıcının aylık özellik talep etme limiti dolduysa işlemini reddeder (Örn: `X/Y hakkınız doldu`).
- **`feature_request_edit_modal`**
  Kullanıcı benzer bulunan talebini düzenlemeyi seçtiğinde girilen yeni veriyi işler ve mevcut talebi güncelleyerek (update_request) kaydeder.

### Etkileşimler (Block Actions)

- **`feature_edit_yes`**: Benzer kayıt ("similar_found") loglandığında kullanıcının karşısına çıkan "Mevcut olanı düzenle" butonudur. Tıklandığında mevcut talebin ID'si ile beraber `feature_request_edit_modal` arayüzünü açar ve önceki butonu içeren uyarı mesajını gizler.
- **`feature_edit_no`**: Kullanıcının benzer talep uyarısı sonrası "Yine de kaydet / Göz ardı et" eylemini gösterir. Sistem bu durumda pending (bekleyen) talebi onaylar (`approve_pending_request`) ve sisteme yeni fikir olarak kaydeder.
- **`feature_edit_cancel`**: İşlemi tamamen iptal etmek için kullanılan butondur. İlgili işlemi durdurur ve temiz bir geri bildirim mesajı ile butonları temizler.

---

## Monitörler

Arka planda çalışan monitör görevleri, belirli aralıklarla yeni veya güncellenen özellik taleplerini tarayarak ilgili duyuru ya da senkronizasyon işlemlerini gerçekleştirir (`feature_monitor.py` vd.).

> *Not: Monitör konfigürasyonları ve çalışma sıklıkları proje ihtiyaçlarına göre güncellenecektir.*
