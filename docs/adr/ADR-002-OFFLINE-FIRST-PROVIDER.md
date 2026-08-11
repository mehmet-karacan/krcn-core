# ADR-002 - Varsayılan offline provider politikası

## Durum

Kabul edildi.

## Bağlam

İndeksleme, embedding, doğrulama veya import sırasında yerel içeriğin otomatik olarak uzak bir servise gönderilmesi kullanıcı beklentisiyle ve veri sahipliği sınırıyla uyuşmaz.

## Karar

KRCN Core varsayılan olarak offline çalışır:

- Ağ erişimi varsayılan olarak reddedilir.
- Host makinedeki başka araçların provider ayarları otomatik keşfedilmez.
- Import, test ve diagnostics işlemleri ağ kullanamaz.
- Uzak provider'lar varsayılan olarak kapalıdır.
- Uzak provider kullanımı her oturum veya işlem için açık opt-in gerektirir.
- Onay öncesinde provider, endpoint, gönderilecek veri kategorileri, işlem kapsamı ve retention varsayımları kullanıcıya gösterilir.

Makinece okunabilir kaynak `config/provider-policy.json` dosyasıdır.

## Sonuçlar

- Yerel deterministic hashing gibi ağsız provider'lar varsayılan olarak kullanılabilir.
- Sessiz provider fallback veya host configuration reuse yasaktır.
- Uzak provider erişimi eklendiğinde ayrıca audit ve redaction kuralları uygulanmalıdır.
