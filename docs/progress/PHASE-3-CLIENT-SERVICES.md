# Faz 3 ortak merge istemci servisleri

## Amaç

Installation inspection, release diff, exact-plan merge, doğrulama ve rollback işlemlerini CLI'a özel olmayan tek bir application service sözleşmesine bağlamak.

## Tamamlanan davranış

1. `installation.inspect` mevcut kurulumu salt okunur inceler.
2. `installation.verify` managed dosyaları, korunan JSON kayıtlarını ve kesintisiz deployment durumunu doğrular.
3. `release.diff` trusted manifest digest, compatibility ve payload doğrulamasından sonra ownership-aware fark üretir.
4. `release.merge` aynı girdilerden deterministic deployment planı üretir.
5. Merge apply yalnızca önceki dry-run sonucundaki exact plan kimliğiyle çalışır.
6. Gerekli user-data veya delete etkileri açık approval kimliği olmadan uygulanmaz.
7. Apply; backup, managed update, migration, derived rebuild, zorunlu verify ve otomatik rollback aşamalarını ortak merge motorunda yürütür.
8. `deployment.rollback` doğrulanmış checkpoint üzerinden önce conflict-safe plan üretir, ardından exact plan ve gerekli onayla geri döner.
9. CLI yalnızca `ServiceRequest` oluşturan ince bir istemcidir.
10. SDK, MCP, plugin, Codex, Claude ve diğer istemciler aynı `KrcnApplicationService` girişini kullanır.

## Güvenlik sonucu

İstemci türü güvenlik davranışını değiştirmez. Hiçbir istemci dry-run, exact-plan, ownership, approval, backup, verification veya rollback kapısını atlayamaz. Genel servis çıktıları fiziksel installation ve release yollarını içermez.

## Doğrulama

Sentetik kurulum ve release testlerinde farklı istemci türlerinin birebir aynı merge planını aldığı kanıtlandı. Ortak servis üzerinden inspect, diff, merge, verify ve rollback zinciri tamamlandı. CLI'ın installation ve release komutlarının aynı servis katmanına yönlendirildiği doğrulandı.

## Sonraki adım

Temiz, no-op, conflict, kesinti, hatalı doğrulama ve rollback senaryolarını Faz 3 entegrasyon paketiyle genişletmek; baseline manifestini ve kapanış raporunu oluşturmak.
