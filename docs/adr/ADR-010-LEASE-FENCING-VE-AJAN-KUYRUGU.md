# ADR 010: Ajan kuyruğu SQLite transaction ve fencing token kullanır

## Durum

Kabul edildi.

## Karar

Her proje kapsülü kendi atomik SQLite ajan kuyruğunu kullanır. Queue item, attempt, lease, resource lock, scheduler event ve projection job aynı transaction sınırında tutulur. Worker sahipliği owner token digest, lease süresi ve her claim işleminde artan fencing token ile doğrulanır.

## Gerekçe

Birden fazla JSON dosyasıyla queue ve lease yönetmek, iki worker'ın aynı işi sahiplenmesi ve eski worker'ın yeni sonucu ezmesi riskini taşır. SQLite `BEGIN IMMEDIATE` claim işlemini atomik hale getirir. Fencing token süresi dolmuş worker'ın heartbeat, completion veya lock release işlemini reddeder.

## Sonuçlar

- Aynı idempotency key ikinci queue item oluşturmaz.
- Tek worker geçerli lease alır.
- Salt okunur kesinti kontrollü tekrar edilebilir.
- Belirsiz write veya network etkisi otomatik tekrarlanmaz.
- Alt ajan ayrı güven rolü kazanmaz.
- Aktif runtime taşınabilir kapsüle girmez.
