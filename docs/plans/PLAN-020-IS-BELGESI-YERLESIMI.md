# Plan 020 - İş belgesi yerleşimi

## Amaç

Talep ve defect belgelerini yıl ve kaynak katmanlarından bağımsız olarak doğrudan iş kimliği altında erişilebilir hale getirmek, mevcut belgeleri kayıpsız korumak ve yeni belgelerin aynı sade sözleşmeyle işlenmesini sağlamak.

## Adımlar

1. Mevcut talep, defect, görev ve ortak belge envanterini salt okunur incele.
2. Kanonik yerleşimi `requests/<id>/<dosya>` ve `defects/<id>/<dosya>` olarak tanımla.
3. Yıl, kaynak, özgün ad ve provenance bilgisini manifest metadata alanlarına taşı.
4. Aynı adlı belgeler için digest tabanlı ve deterministik çakışma kuralı uygula.
5. Eski referansları alias kayıtlarıyla koruyan copy-first migration exact planını geliştir.
6. Doğrudan ID klasörüne eklenen yeni dosyalar için manifest update exact planını ekle.
7. Talep ve defect türünü doğal dil, application ve CLI katmanlarında kayıpsız taşı.
8. Work Item referans güncellemesini, derived index rebuild işlemini ve eski ağaç temizliğini ayrı onay kapılarında tut.
9. GPU Fusion için canlı veriyi değiştirmeyen exact migration planını üret.
10. Kullanıcı onayından sonra migration, belge işleme ve derived doğrulamayı tamamla.

## Kabul ölçütleri

- Kullanıcı ilgili talep veya defect klasöründen doğrudan kimlik klasörüne gidebilir.
- Yıl ve kaynak bilgisi fiziksel yol yerine yapılandırılmış metadata olarak korunur.
- Görev ve ortak belgeler migration sırasında kaybolmaz veya otomatik bölünmez.
- Aynı digestli kopyaların tüm provenance ve eski referansları korunur.
- Farklı içerikli aynı adlar birbirini ezmez.
- İlk migration eski ağacı silmez.
- Work Item, derived index ve cleanup işlemleri ayrı exact plan ve onay sınırlarında kalır.
- Doğrudan ID klasörüne eklenen yeni belge manifest dışında kalmaz.

