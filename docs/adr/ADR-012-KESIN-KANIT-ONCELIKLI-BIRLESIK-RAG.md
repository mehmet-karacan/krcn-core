# ADR 012: Birleşik RAG kesin kanıtı önce kullanır

## Durum

Kabul edildi.

## Karar

Birleşik retrieval sıralamasında yetkili exact kayıtlar semantic benzerlikten önce gelir. Görev durumu ve geçmişi Work Graph JSON kaydından, kaynak uygulama ayrıntısı doğrulanmış dış proje dosyasından, Oracle şema bilgisi immutable metadata revision kaydından okunur.

Varsayılan kapsam tek projedir. Çoklu proje sorgusu açıkça istenir. Stale veya bozuk indeks fail closed olur ve yeniden oluşturma eylemi döndürür.

## Sonuçlar

- `Nerede kaldık?` sorusu vektör benzerliğine göre cevaplanmaz.
- Her sonuç authority, freshness ve evidence açıklaması taşır.
- Semantic sonuç exact kanıtı geçemez.
- Uzak provider kullanımı session onayı olmadan gerçekleşmez.
- Kısmi sonuçta unavailable domain açıkça gösterilir.
