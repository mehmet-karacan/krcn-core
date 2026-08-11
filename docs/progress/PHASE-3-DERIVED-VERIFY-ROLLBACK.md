# Faz 3 derived, verify ve rollback

## Amaç

Trusted derived rebuild etkilerini exact plana bağlamak, başarılı deployment için zorunlu doğrulama uygulamak ve başarısızlıkta kullanıcı değişikliklerini ezmeden geri dönmek.

## Tamamlanan davranış

1. Derived action kimlikleri yalnızca trusted handler registry üzerinden çözülür.
2. Handler yalnızca hedef scope içindeki JSON değerlerini alır; filesystem erişimi verilmez.
3. Derived create, update ve delete etkileri dry-run sırasında exact hashlerle planlanır.
4. İkinci çalıştırmada farklı sonuç üreten handler reddedilir.
5. Managed dosyalar, migration çıktıları, derived çıktılar, korunan JSON kayıtları ve checkpoint içerikleri zorunlu verify aşamasında doğrulanır.
6. Installation state yalnızca diğer doğrulamalar geçtikten sonra atomic olarak commit edilir.
7. Backup manifesti her hedefin deployment öncesi ve beklenen sonrası hashini taşır.
8. Açık rollback yalnızca hedef hâlâ özgün veya beklenen deployment sonrası durumdaysa planlanır.
9. Deployment sonrasında kullanıcı tarafından değiştirilen dosya conflict üretir ve ezilmez.
10. Backup sonrasındaki uygulama veya verify hatası otomatik rollback başlatır.

## Doğrulama sonucu

Sentetik testlerde derived create, update ve delete uygulandı. Başarılı verify installation state'i yeni sürüme taşıdı. Açık rollback core, migration verisi, derived veri ve state'i eski haline getirdi. Zorunlu verify hatasında otomatik rollback aynı sonucu üretti. Deployment sonrası kullanıcı değişikliği korunarak rollback conflict'i oluşturuldu.
