# Faz 3 exact merge dry-run planı

## Amaç

Conflict bulunmayan release diff içindeki bütün görünür etkileri tek bir deterministik plan kimliğine bağlamak ve apply işlemini yalnızca bu planın birebir onayıyla mümkün kılmak.

## Uygulanan davranış

1. Conflict bulunan diff için merge planı üretilemez.
2. Create, update ve delete etkilerinin her biri ownership-aware mutation planına dönüşür.
3. Unchanged dosya için filesystem mutasyonu üretilmez.
4. File mutation kimliği operation, göreli target, ownership ve exact content digest'e bağlıdır.
5. Hedef installation state managed dosyalar, release kimliği, core sürümü, source commit, schema sürümleri ve revision ile önceden hesaplanır.
6. Hedef state'in canonical SHA-256 değeri ayrı runtime mutation planına bağlanır.
7. Manifestteki migration ve derived action kimlikleri yalnızca trusted core registry'de karşılıkları varsa planlanır.
8. Migration source schema sürümü installation state ile uyuşmalıdır.
9. Delete, user-data migration veya açıkça onay gerektiren derived action planın approval kapısını etkinleştirir.
10. Apply çağrısı exact plan kimliğini sağlamadan authorization üretemez.
11. Dry-run doğrulaması her alt mutation planının kendi kimliğine bağlanır.
12. Plan özeti yalnızca göreli target ref ve taşınabilir metadata taşır.

## Koruma sonucu

Plan üretimi hiçbir dosyayı değiştirmez. Migration ve derived action isimleri manifestten doğrudan çalıştırılmaz; yalnızca core içinde önceden kayıtlı trusted descriptor'lara çözülür. Eski veya farklı plan kimliği apply yetkisi oluşturamaz.

## Sonraki adım

Plan uygulanmadan önce etkilenen managed dosyalar ile installation state için recoverable backup oluşturulacak ve kesinti algılayan deployment journal yazılacak.
