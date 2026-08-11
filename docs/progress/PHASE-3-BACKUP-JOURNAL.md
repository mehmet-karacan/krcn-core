# Faz 3 backup ve deployment journal

## Amaç

Her managed apply öncesinde etkilenen mevcut içeriği doğrulanmış local backup'a almak ve işlemin kesildiği aşamayı salt okunur inspection tarafından görülebilen deployment journal ile kaydetmek.

## Uygulanan davranış

1. Backup kapsamı merge planı uygulandıktan sonra değil, final deployment dry-run sırasında belirlenir.
2. Update ve delete hedefleri exact previous hash ile yeniden doğrulanır.
3. Create hedefinin dry-run sonrasında oluşması deployment'ı durdurur.
4. Installation state her deployment'ta backup'a alınır.
5. User-data migration kapsamındaki mevcut dosyalar içerikleri public plana yazılmadan local checkpoint'e alınır.
6. Derived action kapsamı backup'a alınır ve rollback sırasında sonradan üretilen derived dosyaları kaldırabilecek scope kanıtı taşır.
7. Secret sahipliğinde migration descriptor oluşturulamaz ve secret içeriği backup kapsamına girmez.
8. Aynı içeriğe sahip backup dosyaları SHA-256 adresli tek local content nesnesinde tutulur.
9. Backup manifest target ref, mevcutluk, hash, boyut ve content ref taşır; fiziksel kurulum yolunu taşımaz.
10. Backup content, manifest ve her journal durumu ayrı ownership-aware mutation planına bağlanır.
11. Final deployment plan kimliği merge planı ile bütün support mutation kimliklerinin tamamını kapsar.
12. Apply yalnızca final deployment plan kimliği ve gerekli açık onayla authorize edilir.
13. Journal önce `preparing`, doğrulanmış backup tamamlanınca `backed-up` durumuna geçer.
14. Backup kaynağı dry-run sonrasında değişirse core mutasyonu başlamadan işlem durur.

## Koruma sonucu

Backup ve journal yalnızca installation altındaki runtime ile checkpoint alanlarına yazılır. Core, user-data ve derived hedeflerde henüz değişiklik yapılmaz. Backup içeriği Git'e, loga, public plana veya uzak servise gönderilmez.

## Sonraki adım

Doğrulanmış `backed-up` deployment üzerinden managed core create, update ve delete işlemleri atomic olarak uygulanacak; ardından trusted migration handler'ları çalıştırılacak.
