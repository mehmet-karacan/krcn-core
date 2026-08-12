# Faz 13 ajan kuyruğu ve çalışma zamanı tamamlandı

## Sonuç

KRCN Core, proje bazlı atomik ajan kuyruğu, lease, heartbeat, fencing token, attempt geçmişi, resource lock ve güvenli recovery yeteneklerine kavuştu. Alt ajan veya farklı AI istemcisi aynı çalışma sözleşmesine bağlıdır.

## Hazırlanan yetenekler

- Proje başına SQLite scheduler veritabanı oluşturuldu.
- Aynı idempotency key ikinci queue item üretmiyor.
- Claim, lease, attempt ve resource lock tek transaction içinde oluşturuluyor.
- Owner token ham olarak saklanmıyor; yalnız digest kalıcılaştırılıyor.
- Her claim fencing token değerini artırıyor.
- Yanlış owner, süresi dolmuş lease ve eski fencing token reddediliyor.
- Heartbeat lease süresini aynı sahiplik kanıtıyla uzatıyor.
- Salt okunur kesinti retry kapasitesi varsa yeniden kuyruğa alınıyor.
- Belirsiz write, execute veya network etkisi `recovery-required` oluyor.
- Project, task ve göreli path lock çakışmaları denetleniyor.
- Verifier rolünün write etkisi istemesi reddediliyor.
- Runtime completion idempotent projection job oluşturuyor.
- Work Graph tamamlanıp projeksiyon güncellenmeden projection job kapanmıyor.
- Layout v2 orkestrasyon kayıtları proje ve work item bağlamıyla proje kapsülüne yazılıyor.
- `project.resume` queue sayıları, aktif lease ve projection durumunu gösteriyor.

## Taşınabilirlik

Queue, lease, aktif lock ve nonterminal orkestrasyon geçmişi `thin`, `ready` ve bütün home backup paketlerinden çıkarılır. Tamamlanmış orkestrasyon geçmişi `ready` pakette kalabilir. İçe aktarma eski worker sahipliğini veya fencing token değerini etkinleştirmez.

## Korunan sınırlar

- Queue durumu Work Graph görev durumunun yerine geçmez.
- Runtime işlemi user-data onayını veya provider onayını atlamaz.
- Dış proje kaynakları kopyalanmaz veya değiştirilmez.
- Mutlak yollar ve owner token değerleri runtime veritabanına yazılmaz.
- Aktif lease zorla taşınabilir bağlama dönüştürülmez.
