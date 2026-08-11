# Faz 5 görev doğrulama katmanı

## Amaç

Worker yürütme sonucunu, kullanıcı kısıtlarını, kabul ölçütlerini ve doğrulama gereksinimlerini bağımsız ve digest bağlı kanıtlarla değerlendirmek; eksik kanıt varken görevin tamamlanmasını engellemek.

## Tamamlananlar

1. Verifier handler seçimi açık registry kaydına bağlandı; otomatik host veya modül keşfi yapılmadı.
2. Verifier yalnız read ve execute etkileriyle sınırlandı; write etkisi kaydedemedi.
3. Worker checkpoint ve effect journal kimlikleri yeniden hesaplanarak tamper kontrolünden geçirildi.
4. Her worker adımı için tamamlanmış ve çelişmeyen checkpoint zorunlu hale getirildi.
5. Intent içindeki bütün constraint, acceptance criterion ve verification requirement değerleri ayrı doğrulama subject kayıtlarına dönüştürüldü.
6. Kanıtlar verifier step, kapsanan worker adımları ve worker çıktısından gelen observed digest değerlerine bağlandı.
7. Verifier adımının planlanmış acceptance ve verification kapsamını aşması engellendi.
8. Eksik kanıt, başarısız kanıt, eksik worker veya verifier hatası ayrı fail-closed kodlarıyla kaydedildi.
9. Kanıt ve subject kapsamı eksiksiz ve başarılı olmadan `completion_allowed` değeri üretilemedi.
10. Ham gözlem verisi yerine yalnız digest ve açık sınıflandırma tutuldu.

## Güvenlik sonucu

Bir worker adımının `completed` sonucu üretmesi görevin tamamlanması için yeterli değildir. Kullanıcının kısıtları dahil bütün zorunlu subject kayıtları, planlanan verifier kapsamından ve gerçek worker kanıtlarından doğrulanmalıdır. Verifier kendi başına veri değiştiremez ve kanıtsız başarı bildiremez.

## Doğrulama

- Eksiksiz ve başarılı kanıt seti görevin tamamlanmasına izin verdi.
- Eksik veya başarısız subject kanıtı completion değerini kapattı.
- Eksik worker checkpoint completion değerini kapattı.
- Değiştirilmiş checkpoint ve worker çıktısına dayanmayan kanıt reddedildi.
- Write etkisi bildiren verifier handler kaydedilemedi.
- Şema ve tüm depo testleri doğrulandı.

## Sonraki adım

Intent, plan, authorization, checkpoint, journal ve verification kayıtlarını durum makinesi, event geçmişi, resume ve handoff paketiyle kalıcılaştırmak.
