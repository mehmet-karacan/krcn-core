# Faz 25 Effect Ledger domain checkpoint

## Tamamlanan kapsam

- Immutable Effect Claim builder/parser ve schema eklendi.
- Terminal Effect Receipt builder/parser ve schema eklendi.
- Effect Reconciliation builder/parser ve schema eklendi.
- Validation Gate ile exact scope/effect/authorization bagi kuruldu.
- Lease/fencing, idempotency, mutation plan ve provider request kurallari
  fail-closed uygulandi.
- Belirsiz sonuc silent retry yerine reconciliation-required oldu.
- Reconciliation authority ve implicit replay uretmeyecek sekilde sinirlandi.

## Dogrulama

- Effect Ledger testleri: 8/8.
- Validation Gate ile birlikte: 15/15.

## Sonraki checkpoint

Claim ve receipt kayitlari durable exactly-once ledger'a alinacak. Ayni
idempotency key icin conflict, tek terminal receipt, missing receipt recovery
ve atomic replay kurallari persistence katmaninda uygulanacak.
