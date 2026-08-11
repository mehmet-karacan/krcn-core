# ADR-001 - Veri sahipliği ve güncelleme sınırı

## Durum

Kabul edildi.

## Bağlam

KRCN Core sürümleri Git üzerinden dağıtılacak ancak mevcut projeler, belgeler, talepler, görevler, bellek, runtime durumu ve secret'lar kullanıcıya ait kalacak. Core güncellemesi bu verileri sessizce değiştiremez.

## Karar

Tüm kurulum yolları altı sahiplik sınıfından biriyle değerlendirilir:

- `core`: Release tarafından yönetilir ve yalnızca manifestte tanımlıysa değiştirilebilir.
- `runtime`: Güncellemede korunur. Yalnızca açık bir runtime migration ile değiştirilebilir.
- `user-data`: Kullanıcıya aittir ve korunur.
- `derived`: Uyumluysa korunur, gerekirse migrate edilir veya authoritative source üzerinden yeniden oluşturulur.
- `secrets`: Yerel olarak korunur ve Git tarafından yönetilmez.
- `unmanaged`: Varsayılan olarak korunur ve değişiklik için kullanıcı onayı gerekir.

Makinece okunabilir kaynak `config/ownership-manifest.json` dosyasıdır.

## Sonuçlar

- Güncelleme motoru her yolu mutasyondan önce sınıflandırmak zorundadır.
- Manifestte bulunmayan bir yol core olarak kabul edilemez.
- User-data ve secrets sınıfları release paketine eklenemez.
- Derived veri kaybı kullanıcı verisi kaybı gibi ele alınmaz ancak yeniden üretilebilirlik doğrulanır.
