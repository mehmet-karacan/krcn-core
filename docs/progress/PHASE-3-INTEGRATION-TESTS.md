# Faz 3 entegrasyon testleri

## Amaç

Faz 3 bileşenlerinin ortak servis üzerinden birlikte çalıştığını, core güncellemesinin yerel veriyi koruduğunu ve hata durumlarının veri kaybına yol açmadığını hermetik senaryolarla doğrulamak.

## Doğrulanan senaryolar

1. Temiz kurulum inspection, trusted release validation, diff, dry-run, apply ve verify zincirinden geçti.
2. Aynı release ikinci kez planlandığında gerçek no-op üretildi ve hiçbir dosya değişmedi.
3. Yerel olarak değiştirilmiş managed dosya conflict olarak raporlandı ve ezilmedi.
4. Kesintili deployment yeni merge planını engelledi.
5. Yanlış trusted manifest digest'i ilk mutation öncesinde reddedildi.
6. User-data migration exact plan, açık onay, backup ve idempotent handler ile uygulandı.
7. Derived create, update ve delete etkileri exact planla uygulandı.
8. Zorunlu verify hatası otomatik rollback ile özgün duruma döndü.
9. Tamamlanmış deployment açık rollback ile geri alındı.
10. Deployment sonrası kullanıcı değişikliği rollback sırasında conflict üretti ve korunarak bırakıldı.
11. Policy, integration secret reference, yerel secret dosyası ve unmanaged dosya apply ile rollback boyunca değişmedi.
12. CLI, SDK, MCP, plugin, Codex ve Claude aynı merge planı ve güvenlik kapılarını kullandı.
13. Genel servis çıktılarında fiziksel installation veya release yolu bulunmadı.
14. Tüm testler geçici sentetik dizinlerde ve uzak bağlantı kullanmadan çalıştı.

## Sonuç

Faz 3 kabul ölçütlerinin her biri test, hash, exact plan, checkpoint veya istemci parity kanıtıyla doğrulandı. Canlı referans kaynakları ve gerçek kullanıcı kurulumu üzerinde apply çalıştırılmadı.
