# Faz 8 yerel hibrit RAG ve retrieval kalitesi

## Sonuç

Exact, full-text, yerel vektör, dependency, authority ve availability sinyallerini tek bir açıklanabilir sıralamada birleştiren SQLite tabanlı hibrit retrieval katmanı tamamlandı. İndeks aktif kullanıcı evinin yalnız `derived` alanında oluşuyor ve gerektiğinde sıfırdan üretilebiliyor.

Yerel vektör katmanı 192 boyutlu deterministik word ve character trigram feature hashing kullanıyor. Uzak model, ağ, credential veya provider onayı gerektirmiyor. Bu katman gerçek bir dil modeli embedding'i olarak sunulmuyor; yazım hataları ve benzer sözcük biçimleri için ölçülebilir yerel recall desteği sağlıyor.

## Kalite sonucu

Sürümlü dört vakalık değerlendirme setinde:

- recall@5: `1.0`
- mean reciprocal rank: `1.0`
- uzak provider kullanımı: `false`

Her sonuç exact, FTS, vector, dependency, authority ve availability puanlarını ayrı ayrı gösteriyor. Eski katalog digest'i, bozuk vektör, eksik indeks ve değişmiş plan kapalı biçimde hata üretiyor.

## Ölçek ölçümü

Sentetik yerel referans ölçümünde:

| Katalog girdisi | İndeks kurulumu | Sorgu median | Sorgu p95 |
| ---: | ---: | ---: | ---: |
| 101 | 64.186 ms | 10.674 ms | 42.05 ms |
| 1001 | 506.874 ms | 106.25 ms | 161.665 ms |

Sonuçlar Faz 8 eşikleri içinde kaldığı için SQLite FTS5 ve deterministik vektör yaklaşımı kabul edildi. Düzenli katalog boyutu ölçülen 1000 kayıt seviyesini aştığında vektör aday daraltma tekrar değerlendirilecek.

## Korunan sınırlar

Harici proje dosyaları, dış belgeler, veritabanı satırları, fiziksel locator ve secret değerleri indekse alınmıyor. İndeks yalnız KRCN kataloğunda zaten onaylı bilgi metnini türetilmiş biçimde tutuyor. Farklı istemciler aynı application service planını ve sıralama sonucunu kullanıyor.

Bir sonraki adım Linux CI, coverage başlangıç ölçümü, runtime doctor, gözlemlenebilirlik, yönlendirici hatalar ve quickstart çalışmasıdır.
