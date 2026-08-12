# Plan 017 - Birleşik RAG ve sağlamlaştırma

## Durum

Tamamlandı.

## Amaç

Kaynak kod, belge, Work Graph ve Oracle metadata sonuçlarını tek açıklanabilir retrieval akışında birleştirmek ve üretim dayanıklılığını tamamlamak.

## İş paketleri

1. Kesin kayıt, graph, full-text ve vector sorgu sırasını uygula.
2. Proje içi ve projeler arası sorgu kapsamını açık biçimde ayır.
3. Uzak embedding modelleri için onaylı öncelik ve yerel fallback uygula.
4. Stale kaynak ve stale indeks denetimini bütün retrieval türlerine bağla.
5. Bozuk indeks kurtarma ve yeniden oluşturma akışlarını tamamla.
6. Performans, kalite ve açıklanabilirlik baseline'larını güncelle.
7. Windows, macOS ve Linux üzerinde taşıma ve kurtarma senaryolarını doğrula.

## Kabul ölçütleri

- Kesin durum soruları authoritative kayıtlardan cevaplanır.
- Semantic sonuçlar kaynak, revision ve ilişki kanıtı taşır.
- Kaynak değiştiğinde stale indeks sessizce kullanılmaz.
- Provider kullanımı açık session onayı olmadan gerçekleşmez.
