# Faz 20 - İş belgesi yerleşimi

## Durum

Core geliştirmesi tamamlandı. Canlı GPU Fusion migration işlemi kullanıcı onayı bekliyor.

## Tamamlananlar

1. Talep ve defect belgelerindeki gereksiz yıl, source, kaynak ve tekrar kimlik katmanları doğrulandı.
2. V2 yerleşimi `requests/<id>/<dosya>` ve `defects/<id>/<dosya>` olarak tanımlandı.
3. Manifest V2 sözleşmesine iş türü, external ID, belge yılı, özgün ad ve provenance alanları eklendi.
4. Eski ve yeni yerleşimi birlikte okuyabilen geçiş desteği eklendi.
5. Copy-first, stale kontrollü, idempotent ve rollback destekli migration exact planı eklendi.
6. Task ve shared belgeler carry-forward ile korundu.
7. Aynı digestli kopyalarda tüm Work Item, provenance ve legacy alias kayıtları birleştirildi.
8. Farklı digestli aynı adlarda deterministik digest eki kullanıldı.
9. Sayısal olmayan kimlikler için açık `request`, `defect` veya `exclude` karar kapısı eklendi.
10. Doğrudan V2 ID klasörüne bırakılan dosyalar için ayrı manifest update exact planı eklendi.
11. Talep ve defect türü doğal dil, application ve CLI katmanlarında korunur hale getirildi.
12. Work Item işleme, derived rebuild ve eski ağaç temizliği ayrı onaylı işlemler olarak korundu.

## Canlı önizleme

- Toplam manifest kaydı: 372
- Request ve defect kaynak eşlemesi: 305
- Fiziksel V2 hedefi: 304
- Request belgesi: 197
- Defect belgesi: 108
- Korunan task belgesi: 59
- Korunan shared belge: 8
- Farklı içerikli ad çakışması: 3
- Açıkta kalan kimlik kararı: 0
- Hariç bırakılan unassigned belge: 1

## Bekleyen onaylı işlemler

1. Exact migration planını uygula.
2. Güncel Work Item belge referanslarını ayrı exact planla işle.
3. Work Graph ve semantic indexleri yeniden kurup doğrula.
4. Eski V1 ağacını yalnız ayrı cleanup planı ve kullanıcı onayıyla değerlendir.

## Doğrulama

- 50 hedefli domain, application, CLI ve sözleşme testi geçti.
- Tam paket: 840 test geçti, 4 test ortam koşulu nedeniyle atlandı.
- Canlı GPU Fusion envanterinden salt okunur exact plan üretildi.
- Desired V2 manifest JSON Schema ve runtime parser doğrulamasından geçti.
- Repository, context, JSON biçimi, Python derleme, diff ve uzun tire kontrolleri geçti.
- Bağımsız verifier açık P1 veya P2 bulmadı.
