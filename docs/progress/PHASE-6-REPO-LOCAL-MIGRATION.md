# Faz 6 repo-local veri migration

## Sonuç

Eski core clone içindeki `.krcn` verisini repository dışında taşınabilir kullanıcı evine almak için ayrı ve açık migration akışı oluşturuldu. Kurulum, update veya Git pull bu migration'ı otomatik başlatmaz.

## Migration etkileri

1. Repo-local `.krcn` salt okunur incelenir.
2. Repository dışında secret-safe recovery backup hazırlanır.
3. Repository dışında yeni ve boş kullanıcı evi doğrulanır.
4. Backup ve restore etkileri tek migration planında ayrı mutation planları olarak gösterilir.
5. Exact migration planı ve açık kullanıcı approval sonrasında backup yazılır.
6. Backup yeniden doğrulanarak hedef kullanıcı evine atomic restore uygulanır.

## Rollback yaklaşımı

Migration kaynak `.krcn` dizinini silmez, taşımaz veya değiştirmez. Bu nedenle rollback için eski data root tekrar seçilebilir. Yeni hedefin silinmesi otomatik rollback parçası değildir; böylece yanlış hedef seçimi ek veri silme yetkisine dönüşmez.

## Güvenlik sonucu

- Hedef ve backup repository dışında olmak zorundadır.
- Hedef boş olmak zorundadır.
- Proje kaynakları backup veya hedefe kopyalanmaz.
- Secret değerleri taşınmaz.
- Kullanıcı policy'leri aynen korunur.
- Büyük veri yerleşimi değişikliği ayrı migration çıktısı olarak görünür.

