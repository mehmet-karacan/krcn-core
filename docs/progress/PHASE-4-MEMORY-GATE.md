# Faz 4 onay kontrollü Memory Gate

## Amaç

Kalıcı memory üretimini konuşma geçmişinden, çıkarımdan ve otomatik özetten ayırmak; candidate, review, approval, persist, supersede, revoke ve policy promotion işlemlerini birbirine karışmayan kanıtlı adımlar haline getirmek.

## Candidate ve review

1. Memory candidate; köken, önerilen memory kaydı, conflict referansları ve candidate digest taşır.
2. Önerilen kayıt fact, preference, decision veya procedure türlerinden biridir.
3. Conversation summary ve inference yalnız candidate olabilir; kendiliğinden kalıcılaşamaz.
4. Candidate kendi içinden policy promotion başlatamaz.
5. Approved review yalnız kullanıcıdan gelebilir ve candidate digest, session, approval kimliği ile bütün conflict listesini tam olarak bağlar.
6. Rejected veya needs-changes sonucu hiçbir persistence planı üretemez.

## Persistence

Approved review tek başına dosya yazmaz. Memory Gate ayrıca `.krcn/memory/**` kullanıcı verisi için deterministic mutation planı üretir. Yazma işlemi doğrulanmış dry-run ve bu tam plana ait kullanıcı onayı olmadan uygulanamaz.

Persist edilen memory kaydı `approved-memory` provenance taşır. Review digest ayrı evidence olarak eklenir. Memory payload içeriği, revision ve digest yerel store zarfıyla yeniden doğrulanır. Local store doğrudan çağrılsa bile memory sınıfına ait payload sözleşmesini atlayamaz.

## Supersede ve revoke

Supersede ve revoke ayrı lifecycle action kayıtlarıdır. Her action mevcut memory kimliği, revision, content digest, session ve approval kimliğine bağlanır. Supersede yeni memory referansı ister; revoke replacement kabul etmez. Her ikisi de yeni bir user-data mutation planı ve ayrı onay gerektirir.

## Policy koruması

Memory aktif kullanıcı policy'sini değiştiremez veya zayıflatamaz. Bir candidate aktif policy conflict'i taşıyorsa durable memory persistence engellenir. Approved memory'den policy üretmek istenirse ayrı policy payload, ayrı semantic karşılaştırma ve ayrı mutation planı gerekir.

Mevcut bir policy güncellenirken `deny` veya `require-approval` kuralı daha zayıf bir etkiye dönüştürülemez. Bu nedenle örneğin database için `delete` yasağı, memory içeriği ya da yeni bir `allow` kuralıyla kaldırılamaz. Böyle bir değişiklik yalnız policy katmanında açık bir kullanıcı işlemi olarak yeniden ele alınabilir.

## Sonraki adım

Retrieval, context build ve Memory Gate işlemleri ortak application service ile CLI yüzeyine bağlanacak; SDK, MCP, plugin, Codex ve Claude istemcileri aynı plan ve güvenlik davranışını kullanacak.
