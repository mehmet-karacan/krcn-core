# Faz 4 ortak istemci servisleri

## Sonuç

Faz 4 retrieval, context ve memory işlemleri ortak application service sözleşmesine bağlandı. CLI, SDK, MCP, plugin, Codex, Claude ve ileride eklenecek istemciler aynı operasyonları ve güvenlik kapılarını kullanabilecek.

## Tamamlanan işler

1. Bilgi kataloğu, exact retrieval, dependency retrieval ve semantic retrieval ortak servise eklendi.
2. Context package builder, yalnızca açıkça seçilen kalıcı kayıtlarla çalışan ortak `context.build` operasyonuna bağlandı.
3. Memory propose, review, persist ve lifecycle akışları ortak Memory Gate ve mutation gate üzerinden sunuldu.
4. Memory persist için dry-run sonucu, exact plan kimliği ve review ile aynı kullanıcı onayı zorunlu tutuldu.
5. Uzak semantic scorer yalnızca istemci tarafından açıkça enjekte edilebilir duruma getirildi. CLI veya ortam üzerinden örtük sağlayıcı keşfi yapılmadı.
6. `knowledge`, `context-package` ve `memory` CLI grupları, JSON girdisini ortak servise aktaran ince adaptörler olarak eklendi.
7. Application request ve response şemaları yeni operasyonlarla genişletildi.
8. Katalog ve retrieval çıktılarında fiziksel kaynak konumlarının görünmemesi korundu.

## Doğrulama

- Altı istemci türü için exact retrieval ve context çıktılarının eşitliği sentetik kayıtlarla doğrulandı.
- Catalog, dependency ve yerel semantic akışları hermetik testlerden geçti.
- Onay verilmiş olsa bile enjekte edilmiş scorer bulunmadan uzak semantic çağrının başlamadığı doğrulandı.
- Memory propose ve review işlemlerinin yazma yapmadığı, persist ve lifecycle işlemlerinin ise exact plan ve eşleşen onay istediği doğrulandı.
- CLI exact retrieval çıktısının ortak application service çıktısıyla aynı olduğu doğrulandı.

## Korunan alanlar

Testlerin tamamı geçici dizinlerdeki sentetik verilerle çalıştı. Gerçek kullanıcı verisi, yerel referans kaynakları, secret'lar ve makineye özel kaynak konumları okunmadı, değiştirilmedi veya repository'ye eklenmedi.
