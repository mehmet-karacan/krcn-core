# Paket 2 araçtan bağımsız context temeli

## Amaç

KRCN Core deposunu açan farklı yapay zekâların, CLI'ların ve plugin'lerin aynı proje amacı, güvenlik sınırları, aktif plan ve doğrulama akışını kullanmasını sağlamak.

## Tamamlananlar

1. `AI-CONTEXT.md` araçtan bağımsız başlangıç belgesi olarak oluşturuldu.
2. `AGENTS.md` canonical davranış ve güvenlik kaynağı olarak context manifestine bağlandı.
3. `CLAUDE.md`, ortak talimat ve context dosyalarını içe aktaran ince adaptör olarak oluşturuldu.
4. Repository context ve current-work manifestleri ile JSON Schema sözleşmeleri eklendi.
5. Context resolver yalnızca göreli depo yollarını kabul edecek şekilde geliştirildi.
6. Resolver için metin, JSON ve yalnızca doğrulama çıktıları eklendi.
7. Codex, Claude Code, generic AI ve plugin girişlerinin aynı kaynaklara çözüldüğü test edildi.

## Doğrulama

- Mevcut testlerle birlikte toplam 34 test geçti.
- Context resolver doğrulaması başarılı oldu.
- Foundation, secret, taşınabilirlik ve uzun tire kontrolleri bulgu üretmedi.
- Context çıktısında mutlak yol, yerel kaynak konumu veya secret bulunmuyor.
- Giriş belgeleri başlangıç bağlamını gereksiz büyütmeyecek sınırda tutuldu.

## Korunan alanlar

- Yerel proje, belge, iş, talep ve bellek verileri okunmadı veya değiştirilmedi.
- Runtime, derived veri ve secret alanlarına yazılmadı.
- Uzak provider veya ağ bağlantısı kullanılmadı.

## Sonraki adım

Mevcut CLI komutları davranış ve sahiplik etkisine göre envanterlenecek. Kaynak kod takip edilen depo ağacına alınmadan önce Git dışındaki staging alanında arındırılacak.
