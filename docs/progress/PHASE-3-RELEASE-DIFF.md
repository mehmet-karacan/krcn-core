# Faz 3 release diff ve conflict

## Amaç

Doğrulanmış release ile salt okunur installation inspection sonucunu karşılaştırmak, yalnızca güvenli managed core etkilerini sınıflandırmak ve korunması gereken her belirsizliği conflict olarak göstermek.

## Uygulanan davranış

1. State bulunmayan kurulum için release diff üretilmez.
2. Yeni ve boş bir core hedefi `create` olarak sınıflandırılır.
3. State içinde kayıtlı ve değiştirilmemiş hedef `update` veya `unchanged` olarak sınıflandırılır.
4. Delete yalnızca state kaydı, gerçek dosya ve manifestteki previous hash aynı tabana bağlıysa üretilir.
5. Eksik managed dosya `managed-missing` conflict'i oluşturur.
6. Yerel değiştirilmiş managed dosya `managed-modified` conflict'i oluşturur.
7. State dışında var olan release hedefi `unmanaged-overlap` conflict'i oluşturur ve devralınmaz.
8. State dışında silinmek istenen hedef `untracked-delete` conflict'i oluşturur.
9. Delete previous hash ile installation state uyuşmazsa `release-base-mismatch` conflict'i oluşur.
10. Tamamlanmamış deployment kaydı yeni merge için `interrupted-deployment` conflict'i oluşturur.
11. Tamamlanmış migration kimlikleri yeniden planlanmaz.
12. Diff kimliği inspection, trusted manifest, değişiklikler, conflict'ler, migration ve derived action verilerinin tamamına bağlıdır.

## Koruma sonucu

Diff installation veya release içinde hiçbir dosyayı değiştirmez. User-data, secret ve unmanaged dosya içerikleri diff çıktısına girmez. Yerel managed değişiklikler sessizce ezilmez.

## Sonraki adım

Conflict bulunmayan diff, ownership-aware mutation planlarıyla exact merge dry-run kimliğine bağlanacak. Apply farklı veya eski bir planla başlatılamayacak.
