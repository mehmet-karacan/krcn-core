# Faz 20 - İş belgesi yerleşimi

## Durum

Tamamlandı.

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

1. Eski V1 ağacını yalnız ayrı cleanup planı ve kullanıcı onayıyla değerlendir.

## Uygulanan canlı migration

- Onaylanan exact plan: `603e50d76430fd9b210cc30341e7bbed18ea8c34374ddb23df218d2d038a19e1`
- 303 canonical V2 hedefi copy-first yöntemiyle oluşturuldu.
- Eski V1 belgeler silinmedi.
- V2 manifest yazıldı ve runtime parser ile doğrulandı.
- Migration tekrarının no-op olduğu doğrulandı.
- Sonraki Work Item işleme planı: `fde73608cda75c6a299611f2e28788e536fc5be49c7454368f3c594c9b11771b`
- İkinci plan 362 belgeyi 115 Work Item ile ilişkilendiriyor ve 61 Work Item revizyonu hazırlıyor.
- İkinci exact plan kullanıcı onayıyla uygulandı.
- 61 Work Item yeni V2 belge referanslarıyla güncellendi.
- Work Graph projection güncellendi.
- Semantic index 116 vektörle yeniden kuruldu; 61 kayıt işlendi ve 55 kayıt yeniden kullanıldı.
- İşlem tekrarının 0 değişiklik ve 0 incoming belge ile no-op olduğu doğrulandı.
- `893614` exact aramada ilk sırada ve semantic index durumu `current` olarak doğrulandı.

## Doğrulama

- 51 hedefli domain, application, CLI ve sözleşme testi geçti.
- Tam paket: 842 test geçti, 4 test ortam koşulu nedeniyle atlandı.
- Canlı GPU Fusion envanterinden salt okunur exact plan üretildi.
- Desired V2 manifest JSON Schema ve runtime parser doğrulamasından geçti.
- Repository, context, JSON biçimi, Python derleme, diff ve uzun tire kontrolleri geçti.
- Bağımsız verifier açık P1 veya P2 bulmadı.
