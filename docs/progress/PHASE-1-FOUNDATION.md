# Faz 1 foundation ilerleme kaydı

## Durum

Repository ve veri sahipliği temeli tamamlandı. Mevcut core kodunun sanitize edilerek aktarılması henüz başlamadı.

## Tamamlanan çalışmalar

### Veri sahipliği

`config/ownership-manifest.json` ile altı sahiplik sınıfı tanımlandı:

- core;
- runtime;
- user-data;
- derived;
- secrets;
- unmanaged.

Manifestte bulunmayan yollar varsayılan olarak unmanaged kabul edilir, korunur ve değişiklik için kullanıcı onayı gerektirir.

### Offline provider politikası

`config/provider-policy.json` şu varsayılanları uygular:

- Ağ erişimi reddedilir.
- Import, test ve diagnostics işlemleri ağ kullanamaz.
- Host makinedeki başka provider ayarları otomatik keşfedilmez.
- Uzak provider'lar varsayılan olarak kapalıdır.
- Uzak provider kullanımı açık opt-in ve veri kapsamı bildirimi gerektirir.

### Import politikası

`config/import-policy.json` ile import öncesi zorunlu kapılar tanımlandı. Tarayıcı şu kategorileri engeller:

- cache, bytecode, database, secret ve IDE dosyaları;
- Windows ve POSIX kullanıcı dizinleri;
- private key ve GitHub token'ları;
- e-posta ve IP adresleri;
- uzun tire karakterleri;
- belirlenen boyutun üzerindeki metin dosyaları;
- UTF-8 olmayan metin dosyaları.

### Doğrulama aracı

`tools/verify_repository.py` iki çalışma biçimini destekler:

1. Repository foundation yapılandırmasını ve Git adaylarını doğrular.
2. `--source` ile verilen import adayını aynı politika üzerinden tarar.

Araç yalnızca Python standart kütüphanesini kullanır ve ağ erişimi yapmaz.

## Test sonucu

- Python syntax doğrulaması geçti.
- Foundation unit testleri 13/13 geçti.
- Repository portability ve secret taraması temiz geçti.
- Mevcut baseline adayı yeni import kapısından geçemedi. Toplam 35 bulgu kaydedildi:
  - 8 engellenmiş dosya yolu veya türü;
  - 14 makineye özel Windows yolu;
  - 6 IP adresi;
  - 7 uzun tire karakteri.

Bu sonuç beklenen davranıştır. Baseline doğrudan kopyalanmayacak.

## Karar kayıtları

- `ADR-001`: Veri sahipliği ve güncelleme sınırı.
- `ADR-002`: Varsayılan offline provider politikası.

## Sonraki aktarım kapısı

Bir sonraki geliştirme adımı sanitize edilmiş core aktarımıdır. İşlem şu sırayla yürütülecek:

1. Portable şema, agent, policy ve launcher adayları geçici staging alanına alınır.
2. Her dosya yeni import tarayıcısından geçirilir.
3. Makineye özel ve kullanıcıya ait içerik kaldırılır.
4. Monolitik CLI içindeki otomatik ağ davranışı kapatılır.
5. Canlı projelere bağlı testler sentetik fixture ile değiştirilir.
6. Kullanıcıya yalnızca temizlenmiş staged diff gösterilir.
7. Onaylanan dosyalar core repository yapısına eklenir.
