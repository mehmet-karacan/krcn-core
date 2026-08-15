# Faz 21 - Retrieval golden set ve ölçek fixture'ları

## Durum

Tamamlandı.

## Amaç

Retrieval kalitesini dört küçük sentetik örnekten çıkarıp gerçek kullanıcı sorgu türleri, güvenlik sınırları ve büyük veri ölçeği için ölçülebilir hale getirmek.

## Tamamlananlar

1. Exact ID, yazım hatası, iş kavramı, Java sembolü, bağımlılık etkisi, devamlılık, PL/SQL, proje izolasyonu ve stale revision sınıflarını kapsayan sürümlü golden set eklendi.
2. Recall@K, MRR, nDCG@K, exact top-one, kritik vaka, proje sızıntısı, stale kabulü ve p50/p95 ölçümleri tek evaluator altında toplandı.
3. Eksik vaka, yinelenen hit, fiziksel yol, secret benzeri sorgu ve kapsam dışı proje kanıtı fail-closed hale getirildi.
4. 128, 1.000, 10.000 ve 50.000 kayıtlık sentetik fixture profilleri eklendi. Büyük corpus depoya yazılmıyor; ihtiyaç halinde lazy ve deterministik üretiliyor.
5. `retrieval.evaluate-golden` ve `retrieval.scale-fixture` istemciden bağımsız, salt okunur application işlemleri olarak bağlandı.
6. Golden set ve ölçek politikaları foundation doğrulamasına ve repository context kataloğuna alındı.

## Güvenlik sınırı

- Provider çağrısı yapılmaz.
- Proje kaynak içeriği fixture veya sonuç içine kopyalanmaz.
- Ölçüm yetki, onay veya model seçimi kazandırmaz.
- Remote retrieval gözlemi varsa kendi provider gate kanıtı ayrıca zorunludur.
- Golden sonuç mevcut davranışı kör biçimde kutsamaz; beklentiler kullanıcı ihtiyacı ve güvenlik invariantlarından gelir.

## Sonraki adım

Application ve CLI iç bölünmesini facade davranışını bozmadan tamamlamak, ardından Faz 21 kapanış doğrulamasını çalıştırmak.
