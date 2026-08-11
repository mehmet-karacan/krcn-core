# Faz 5 typed intent modeli

## Sonuç

Doğal dil talebini açık görev sözleşmesine dönüştüren deterministic ve secret-safe typed intent modeli oluşturuldu.

## Uygulanan kurallar

1. Ham kullanıcı talebi kalıcı intent içine alınmadı; yalnızca SHA-256 digest değeri taşındı.
2. Goal yalnızca explicit kullanıcı girdisinden gelebilir duruma getirildi.
3. Scope, sources, constraints, acceptance criteria ve verification requirements değerleri explicit kullanıcı girdisi ile safe assumption olarak ayrıldı.
4. Safe assumption yalnızca küçük etkili, geri alınabilir ve gerekçesi kayıtlı olduğunda kabul edildi.
5. Scope, authority, user-data, external system veya irreversible effect belirsizliği planning işlemini durduran clarification kaydına dönüştürüldü.
6. Ownership impact açık ownership sınıflarıyla sınırlandı.
7. Aynı talep ve extraction girdisi aynı intent digest değerini üretti.
8. Secret benzeri içerik intent oluşturulmadan reddedildi.

## Doğrulama

- Türkçe doğal dil talebi deterministic intent kaydına dönüştürüldü.
- Alan sırası değiştiğinde aynı normalized çıktı ve digest üretildi.
- Ham talebin genel çıktıda bulunmadığı doğrulandı.
- Material ambiguity planning öncesinde `needs-clarification` durumu üretti.
- Geri alınamaz safe assumption, çıkarımla üretilmiş goal, eksik assumption kanıtı, secret içerik ve değiştirilmiş digest reddedildi.

## Korunan alanlar

Testler yalnızca sentetik taleplerle çalıştı. Gerçek görev, kullanıcı verisi, source binding, policy, secret, tool veya uzak provider kullanılmadı.
