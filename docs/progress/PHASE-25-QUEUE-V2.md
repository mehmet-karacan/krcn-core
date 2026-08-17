# Faz 25 Agent Runtime Queue v2 checkpoint

## Tamamlanan kapsam

- Runtime queue schema version 2 additive migration eklendi.
- Mevcut scheduler-v1 SQLite dosya yolu ve v1 satirlari korundu.
- Migration yalniz ayri exact `runtime.queue.migrate-v2` planiyla uygulanir;
  read veya planning sirasinda sessiz schema mutation yapilmaz.
- Queue item'a ledger-required, Validation Gate, Effect Claim ve Effect Receipt
  baglari eklendi.
- Ledger-required adim claim ve completed receipt olmadan tamamlanamaz.
- Claim/receipt baglari durable Effect Ledger kaydindan yeniden okunup lease,
  attempt, queue ve fencing token ile exact dogrulanir.
- Eski adimlar `ledger_required=0` ile ayni davranisi korur.
- Doctor schema v2 ve secret-safe kolon sinirini denetler.
- Application, CLI ve transport contractlarina migration ve effect bind
  operasyonlari eklendi.

## Dogrulama

- Agent Runtime: 9/9.
- Application, CLI ve registry yakin regresyonlariyla: 29/29.

## Sonraki checkpoint

Worker/DAG adapterlari Validation Gate, durable claim ve terminal receipt
uretecek; Workflow Step Receipt ve Agent Result Envelope bu kimliklere exact
baglanacak.
