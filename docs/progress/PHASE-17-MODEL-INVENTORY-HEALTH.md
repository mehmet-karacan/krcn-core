# Faz 17 model envanteri ve sağlık yaşam döngüsü

## Durum

Tamamlandı.

## Sonuç

Kullanıcının erişebildiği modeller artık kimlik bilgisi ve bağlantı adresi saklanmadan genel model envanterine alınabiliyor. Envanter kullanıcı verisi olarak exact-plan ve açık onayla yazılıyor.

Model sağlık kontrolü, gerçek proje içeriğini kullanmayan sentetik bir istekle çalışıyor. Uzak sağlayıcıya istek göndermek için oturuma bağlı açık sağlayıcı onayı gerekiyor. Planlama sırasında uzak çağrı yapılmıyor ve kimlik bilgisi okunmuyor.

## Uygulanan sınırlar

- Model envanteri proje kapsüllerinden bağımsız ve global tutuluyor.
- Model kaydı proje kapsülüne yanlışlıkla yazılamıyor.
- Token, parola, API anahtarı ve bağlantı adresi envantere alınmıyor.
- Başarılı sağlık kontrolü modele yetki veya proje yeterliliği kazandırmıyor.
- İki ardışık hata modeli karantinaya alıyor.
- Bekleme süresi dolunca model yeniden aday oluyor ve tekrar test edilmesi gerekiyor.
- Envanter veya sağlık politikası değişirse eski sonuç geçersiz sayılıyor.
- Kalıcı sağlık kaydı yalnız durum, süre, hata sınıfı ve doğrulama özetlerini taşıyor.
- İstek ve yanıt metni, bağlantı adresi ve kimlik bilgisi kalıcı kayda yazılmıyor.
- Taşınabilir yedek, global kullanıcı model envanterini kapsıyor; türetilmiş sağlık kaydı yeniden üretilebilir kalıyor.

## Yerel envanter sonucu

OpenCode yapılandırmasında görülen 18 model, kimlik bilgisi taşımayan envantere alındı. Önceki kısa karşılaştırmada başarısız olan iki MiniMax adayı devre dışı bırakıldı. Bu nedenle 16 model sağlık ve yeterlilik değerlendirmesine adaydır.

Gerçek uzak sağlık çağrıları bu aşamada otomatik başlatılmadı. Her model çağrısı için ayrı exact plan ve sağlayıcı onayı korunuyor.

## Sonraki adım

Proje yetkinlik profillerinden analiz, mimari, geliştirme, doğrulama ve diğer uzmanlıklar için güvenli mikro benchmark paketleri üretmek ve sonuçları proje özel model atamalarına bağlamak.
