# Faz 5 worker yürütme katmanı

## Amaç

Yalnızca birebir yetkilendirilmiş görev adımlarını açık handler kayıtları üzerinden çalıştırmak; kesinti ve tekrar çağrılarında etkilerin güvenli, izlenebilir ve idempotent kalmasını sağlamak.

## Tamamlananlar

1. Handler seçimi açık registry kaydına bağlandı; host, modül veya ortam taraması yapılmadı.
2. Handler capability ve side effect sınırları çalıştırmadan önce görev adımıyla karşılaştırıldı.
3. Worker isteği task, plan, authorization, step, handler ve input digest alanlarından üretilen idempotency key'e bağlandı.
4. Input ve sonuç özetlerinde boyut sınırı ile hassas bilgi kontrolü uygulandı.
5. Worker bağımlılıkları tamamlanmış checkpoint kayıtlarıyla doğrulandı.
6. Tamamlanmış aynı istek ikinci kez handler çağırmadan önceki checkpoint ve effect journal kaydını döndürdü.
7. Tamamlanmış bir adımın farklı input ile yeniden bağlanması reddedildi.
8. Başarısız checkpoint aynı idempotency key ile yeniden denenebilir hale getirildi.
9. Write etkileri exact mutation plan, network etkileri exact provider request kimliği olmadan kabul edilmedi.
10. Handler sonucu plan dışı etki bildirirse adım fail-closed kapatıldı ve hata metni yerine yalnız failure digest kaydedildi.

## Güvenlik sonucu

Task plan veya capability registry tek başına kod çalıştırmaz. Yürütme için mevcut task authorization, açık handler kaydı, tamamlanmış bağımlılıklar ve birebir effect kapsamı birlikte gereklidir. Worker kendi capability alanını, mutation kapsamını veya provider yetkisini genişletemez.

## Doğrulama

- Başarılı adımın tekrar çağrısında handler yalnız bir kez çalıştı.
- Kesintiye uğrayan adım aynı idempotency key ile başarıyla tekrarlandı.
- Eksik bağımlılık ve değiştirilmiş input reddedildi.
- Kayıtsız handler, plan drift ve plan dışı etki fail-closed sonuç verdi.
- Hassas input kalıcı yürütme kaydı üretilmeden reddedildi.
- Şema ve tüm depo testleri doğrulandı.

## Sonraki adım

Worker journal ve checkpoint kanıtlarını kabul ölçütleriyle karşılaştıran bağımsız verifier katmanını oluşturmak.
