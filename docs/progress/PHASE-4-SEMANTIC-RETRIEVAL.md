# Faz 4 provider kontrollü anlamsal bilgi getirme

## Amaç

Anlamsal aramayı exact ve dependency retrieval katmanlarından sonra kullanılabilecek ayrı bir seçenek olarak sunmak; çevrim dışı temel davranışı korumak ve uzak provider kullanımını mevcut disclosure ile oturum onayı kapısının arkasında tutmak.

## Yerel temel davranış

Provider açıkça seçilmezse mevcut politika yalnız `deterministic-hashing` yerel provider kimliğini seçer. Bu yol ağ kullanmaz ve veriyi cihaz dışına çıkarmaz. Yerel sonuç, Unicode ile normalize edilmiş sözcük kümelerinin kesişim oranını kullanır. Bu davranış gerçek embedding eşdeğeri gibi sunulmaz; deterministik ve çevrim dışı bir fallback olarak işaretlenir.

## Uzak provider sınırı

1. Provider, endpoint, gönderilecek veri sınıfları, işlem kapsamı, retention varsayımı ve session kimliği önceden disclosure kaydına bağlanır.
2. Sorgu metni ile katalog metninin gönderileceği açıkça belirtilir.
3. Provider isteği sorgudaki provider, remote ve session değerleriyle tam eşleşir.
4. Mevcut provider gate aynı request ve session için açık onay görmeden adapter çağrılmaz.
5. Onaydan sonra bile KRCN Core kendiliğinden ağ istemcisi bulmaz; uzak scorer ilgili adapter tarafından açıkça sağlanmalıdır.
6. Provider yalnız açıklanmış aday kayıtlar için sıfır ile bir arasında score döndürebilir.

## Sonuç ve gizlilik

Sonuç query, catalog, candidate, provider request ve result digest değerlerini taşır. Genel sonuçlarda sorgu metni, katalog payload içeriği ve endpoint bulunmaz. Eski veya erişilemeyen kayıtlar varsayılan aday kümesine alınmaz. Hiçbir semantic işlem kullanıcı verisi yazmaz veya policy kısıtlarını değiştirmez.

## Sonraki adım

Exact, dependency ve semantic sonuçları authority, evidence ve sabit bütçe kurallarıyla birleştiren context package builder oluşturulacak.
