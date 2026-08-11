# Faz 1 foundation ilerleme kaydı

## Durum

Bu kayıt Faz 1'in ilk foundation dilimini belgeler. Repository ve veri sahipliği temeli bu dilimde tamamlandı. Faz 1'in tamamı daha sonra arındırılmış core, ortak context ve CLI baseline paketleriyle kapatıldı. Güncel kapanış sonucu `docs/progress/PHASE-1-COMPLETION.md` içindedir.

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

## Tamamlanma bağlantısı

Bu kayıtta belirtilen aktarım kapıları tamamlandı. Eski monolitik CLI doğrudan alınmadı; arındırılmış modüler baseline yeni core kodu olarak geliştirildi. Canlı proje veya kullanıcı verisi aktarılmadı.
