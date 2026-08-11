# Faz 6 taşınabilir kullanıcı evi

## Sonuç

KRCN user-data, policy, knowledge, memory, derived kayıt ve runtime durumu için repository'den bağımsız tek kullanıcı evi çözümü oluşturuldu.

## Çözüm sırası

1. CLI ile açıkça verilen `--data-root`.
2. `KRCN_HOME` ortam değişkeni.
3. Windows, macOS veya XDG platform varsayılanı.

Açık seçim geriye dönük uyumluluk için korunur. Ortam değişkeninde göreli yol kabul edilmez. Filesystem kökü, symlink veya dosya hedefi kullanıcı evi olamaz.

## Güvenlik sonucu

- Varsayılan kullanıcı verisi artık Git clone dizinine bağlı değildir.
- Yeni core clone aynı `KRCN_HOME` değerini kullanarak mevcut KRCN bağlamını açabilir.
- Fiziksel kullanıcı evi yolu public summary içine yazılmaz.
- Dış proje kaynaklarının yeri veya içeriği bu adımda değiştirilmez.

