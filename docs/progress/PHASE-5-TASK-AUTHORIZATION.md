# Faz 5 görev yetkilendirme kapıları

## Amaç

Deterministik görev planını çalıştırılabilir saymadan önce mevcut capability, kullanıcı politikası, sahiplik, mutasyon ve provider kapılarına bağlamak.

## Tamamlananlar

1. Yetkilendirme, task intent ve capability selection ile yeniden üretilen birebir plan kimliğine bağlandı.
2. Her worker adımı için açık resource, operation ve scope kaydı zorunlu hale getirildi.
3. Etkili kullanıcı politikaları mevcut deny-overrides kuralıyla değerlendirildi.
4. `deny` kararının başka bir `allow` kuralı veya orchestrator onayıyla geçersiz kılınması engellendi.
5. Veri tabanı işlemleri için eşleşen kullanıcı politikası zorunlu tutuldu; policy bulunmayan işlem fail-closed kaldı.
6. Her yazan worker adımı, sahiplik manifestiyle doğrulanan bir mutation planına bağlandı.
7. Dry-run ve kullanıcı onayı mevcut mutation gate üzerinden birebir alt plan kimliğiyle doğrulandı.
8. Local ve remote provider istekleri mevcut offline-first provider gate üzerinden doğrulandı.
9. Remote provider onayı request, session ve task plan kimliklerinin tamamına bağlandı.
10. Kullanıcı onayının plan dışında trigger, mutation veya provider yetkisi eklemesi engellendi.

## Güvenlik sonucu

Kullanıcının veri tabanında yalnızca `SELECT` çalıştırılması ve `DELETE` işleminin yasaklanması gibi açık politikaları orchestrator planı, daha gevşek başka bir kural veya genel kullanıcı onayı ezemez. Plan yalnızca mevcut alt güvenlik kapılarının tümü aynı kapsam için olumlu sonuç verdiğinde yürütme yetkisi kazanır.

## Doğrulama

- Salt okunur ve policy tarafından izin verilen görev kullanıcı onayı olmadan yetkilendirildi.
- User-data yazımı exact task plan, exact mutation plan ve doğrulanmış dry-run olmadan reddedildi.
- Birlikte bulunan `deny` ve `allow` kurallarında `deny` etkili kaldı.
- Remote provider için disclosure, request ve session kapsamı birebir doğrulandı.
- Worker operation kaydı eksik plan fail-closed reddedildi.
- Şema ve tüm depo testleri doğrulandı.

## Sonraki adım

Yetkilendirilmiş worker adımlarını checkpoint, effect journal ve idempotency anahtarıyla çalıştıran yürütme katmanını oluşturmak.
