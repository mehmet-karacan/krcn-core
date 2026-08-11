# Faz 3 managed apply ve migration

## Amaç

Doğrulanmış backup sonrasında yalnızca exact plan içindeki managed core dosyalarını uygulamak ve trusted, versioned, idempotent migration dönüşümlerini kontrollü biçimde çalıştırmak.

## Uygulanan davranış

1. Apply öncesinde release manifest digest, release kimliği ve source commit merge planıyla yeniden eşleştirilir.
2. Bütün core target ve payload kanıtları ilk yazmadan önce topluca yeniden doğrulanır.
3. Create hedefi sonradan oluşmuşsa işlem durur.
4. Update ve delete hedefi previous hash değerinden sapmışsa işlem durur.
5. Upsert payload exact target hash ve byte boyutundan sapmışsa işlem durur.
6. Core create ve update atomic replace ile uygulanır ve sonuç hashleri doğrulanır.
7. Core delete yalnızca backup ve delete approval kanıtıyla uygulanır.
8. Migration kimliği yalnızca trusted handler registry üzerinden çözülür.
9. Migration handler filesystem erişimi almaz; yalnızca JSON değerini dönüştürür.
10. Handler ikinci kez kendi çıktısına uygulandığında aynı canonical sonucu üretmelidir.
11. Her migration write previous ve target SHA-256 ile final deployment planına bağlanır.
12. Generic migration yeni kayıt oluşturamaz, kayıt silemez, secret veya policy alanına erişemez.
13. User-data migration açık onay gerektirir.
14. Bütün migration target'ları ilk yazmadan önce yeniden doğrulanır ve atomic olarak güncellenir.
15. Installation state bu aşamada henüz değiştirilmez.

## Koruma sonucu

Manifest içeriği kod olarak çalıştırılmaz. Core dosyası yalnızca release payload kanıtıyla, user-data kaydı yalnızca trusted migration çıktısı ve açık onayla değişebilir. Her iki alan da önceden oluşturulmuş local backup ile geri alınabilir.

## Sonraki adım

Trusted derived action'lar çalıştırılacak, installation ve korunan veri doğrulanacak, başarılı state commit edilecek; herhangi bir hatada otomatik rollback uygulanacak.
