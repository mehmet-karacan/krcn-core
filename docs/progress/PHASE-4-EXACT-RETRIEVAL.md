# Faz 4 kesin eşleşmeli bilgi getirme

## Amaç

Bilgi kataloğunda ağ veya model kullanmadan, aynı sorgu ve aynı katalog için her zaman aynı kayıtları aynı sırada üreten bir exact retrieval katmanı oluşturmak.

## Eşleşme kuralları

1. Kayıt kimliği, mantıksal konu referansı ve konu yolu tam eşleşir.
2. Başlık, takma ad ve anahtar alanları Unicode NFC ile normalize edilir ve varsayılan olarak büyük ve küçük harf ayrımı olmadan tam eşleşir.
3. Metin alanı, sorgu ifadesinin değişmeden ve kesintisiz biçimde geçtiği kayıtları eşleştirir.
4. Büyük ve küçük harf duyarlılığı sorguda açıkça seçilebilir.
5. Eşleşme alanları sorgu sözleşmesinde belirtilir; semantic veya belirsiz alanlar kabul edilmez.

## Sıralama ve kanıt

Sonuçlar eşleşme kesinliği, availability, authority, revision, evidence sayısı, mantıksal konu ve kayıt kimliği sırasıyla deterministik olarak sıralanır. Her sonuç katalog digest, sorgu digest, kayıt digest, revision, authority, availability, eşleşen alanlar ve evidence bilgilerini taşır.

Varsayılan sorgu yalnız `current` kayıtları döndürür. Eski, superseded, archived veya source binding sorunu olan kayıtlar ancak sorguda açıkça istendiğinde durumlarıyla birlikte görünür.

## Güvenlik sonucu

Arama source binding locator değerini okumaz, fiziksel yolu sonuçlara eklemez ve provider çağrısı yapmaz. Genel sonuç sözleşmesi payload metnini taşımaz. Bu adım hiçbir kullanıcı verisi yazmaz ve mevcut politika veya kaynak yetkisini değiştirmez.

## Sonraki adım

Exact retrieval sonuçlarının proje, modül, belge, karar, görev ve kaynak ilişkileri üzerinden kontrollü biçimde genişletileceği dependency graph retrieval katmanı oluşturulacak.
