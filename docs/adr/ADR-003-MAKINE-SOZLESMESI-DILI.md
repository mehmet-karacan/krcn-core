# ADR-003 - Makine sözleşmelerinin dili

## Durum

Önerildi. Paket 1 kullanıcı onayıyla depoya alındığında kabul edilmiş sayılacak.

## Bağlam

Eski şema, engine, policy ve agent tanımlarında Türkçe, Türkçe karakter içermeyen Türkçe ve İngilizce alan adları birlikte kullanılıyor. Bazı kayıtlar bağlı oldukları şemalarla aynı alan tiplerini kullanmıyor. Bu durum doğrulamayı ve başka araçların sözleşmeleri yorumlamasını zorlaştırıyor.

KRCN Core farklı CLI'lar ve yapay zekâlar tarafından ortak bir çekirdek olarak kullanılacak. Makine sözleşmelerinin tek anlam taşıması, taşınabilir olması ve insan operasyon kayıtlarından ayrılması gerekiyor.

## Karar

1. Makinece okunan alan adları, enum değerleri, kimlikler ve açıklamalar İngilizce olacak.
2. Makine sözleşmeleri JSON Schema 2020-12 biçiminde tutulacak.
3. KRCN Core şema kimlikleri `urn:krcn:schemas:*` ad alanını kullanacak.
4. Planlar, ilerleme kayıtları, görev takibi, commit mesajları ve kullanıcıya sunulan operasyon raporları Türkçe olacak.
5. Eski alan adları doğrudan core sözleşmesine taşınmayacak. Gerekirse Paket 2 içindeki açık bir uyumluluk dönüştürücüsü tarafından ele alınacak.
6. Aynı sözleşmenin Türkçe ve İngilizce iki ayrı kaynak doğrusu oluşturulmayacak.

## Sonuçlar

- Şema ve kayıt tanımları başka araçlar tarafından daha tutarlı yorumlanabilecek.
- Eski CLI doğrudan yeni sözleşmeleri tüketemeyebilir. Bu uyumluluk Paket 2'de test edilerek sağlanacak.
- İnsan operasyon belgelerinde doğal Türkçe kullanımı devam edecek.
