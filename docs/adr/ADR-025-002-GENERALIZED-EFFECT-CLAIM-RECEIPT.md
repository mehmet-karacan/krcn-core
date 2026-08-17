# ADR-025-002: Generalized Effect Claim ve Terminal Receipt

## Durum

Kabul edildi.

## Karar

Write, execute ve network etkileri durable Effect Ledger'da atomik claim
alir. Claim Validation Gate, authorization, idempotency key, execution
identity, queue attempt, lease ve fencing token'a baglidir. Handler ancak
durable claim queue'ya baglandiktan sonra calisabilir.

Her claim en fazla bir terminal receipt alir. Completed receipt result digest;
basarisiz receipt sanitize kategori/digest tasir. Claim olup receipt olmayan
durum sessiz retry edilmez ve recovery-required olur. Belirsiz dis durum ayri
reconciliation kaydiyla siniflandirilir; reconciliation implicit replay yetkisi
vermez.

## Sonuclar

- Ayni idempotency key ikinci etki cagrisina izin vermez.
- Stale fence receipt veya queue completion yazamaz.
- Queue schema v2 additive ve forward-only migration kullanir.
- Eski v1 queue satirlari korunur; yeni authority kaydi turetilmez.
- Worker, Generic DAG ve native structured result ayni claim/receipt bagini
  Agent Result Envelope'a tasir.
