# Faz 4 kaynak ve bilgi kataloğu

## Amaç

Yetkili kaynakları fiziksel konumlarını açığa çıkarmadan source binding kayıtlarına bağlamak, düzenlenmiş bilgi kayıtlarını kesin kaynak sürümleriyle ilişkilendirmek ve güncellik durumunu aynı girdide aynı sonucu verecek biçimde üretmek.

## Uygulanan davranış

1. Katalog yalnızca `authoritative-source` ve `knowledge` bilgi sınıflarını kabul eder.
2. Yetkili kaynak kaydı, mantıksal source kimliği ile source binding kimliğini ve sürümünü ayrı taşır.
3. Kaynağın kendi revision kimliği ve digest değeri, kayıt içindeki kanıtla tam olarak eşleşir.
4. Fiziksel locator katalog özetine veya Git deposuna alınmaz.
5. Aynı konu için birden fazla güncel yetkili kaynak varsa katalog belirsizliği reddeder.
6. Source binding yoksa, değişmişse veya okuma yetkisiyle çelişiyorsa durum açıkça gösterilir.
7. Güncel kaynak revision veya digest değeri değiştiğinde eski kanıta bağlı bilgi kaydı `stale` olur.
8. Katalog sırası authority, availability, logical subject, revision ve kayıt kimliği üzerinden deterministik üretilir.
9. Katalog özeti payload içeriğini taşımaz; yalnız kimlik, revision, digest, lifecycle, availability ve evidence gösterir.
10. Yetkili kaynak ve düzenlenmiş bilgi kayıtları `.krcn/knowledge/**` altında korunmuş kullanıcı verisidir; her yazma işlemi doğrulanmış dry-run ve açık onay gerektirir.

## Koruma sonucu

Kaynağa ait gerçek konum kullanıcı verisi alanında kalır. Katalog kaynak içeriğini kopyalamaz, onaysız kayıt yazmaz ve eski kanıtı güncel gerçek gibi sunmaz. Böylece farklı bir CLI, yapay zekâ veya eklenti aynı mantıksal katalog üzerinden çalışırken veri sahipliği ve kullanıcı politikaları değişmeden kalır.

## Sonraki adım

Katalog üzerinde kimlik, başlık, anahtar, takma ad ve tam metin alanlarını kullanan çevrim dışı, deterministik exact retrieval katmanı oluşturulacak.
