# Faz 23-28 final handoff

## Tamamlanan mimari

- Faz 23: Adaptive Routing shadow decision ve karşılaştırma.
- Faz 24: Agent Result Envelope, Workflow Step Receipt, fan-in ve trace.
- Faz 25: Validation Gate, generalized Effect Ledger, Queue V2 ve recovery.
- Faz 26: Outbound Assurance ve detached Worktree Sandbox.
- Faz 27: Markdown Implementation Delivery, rollback, verifier ve route enforcement.
- Faz 28: Team Runtime need gate; mevcut profil için kanıtlı `deferred`.

## Senkronizasyon sınırı

`krcn-core-dev` main, bu handoff commit'iyle mimari kaynak olacaktır. Bir sonraki
iş yalnız ayrı bir exact eşitleme planıdır: `production-krcn-core` kaynağının
mevcut dirty durumu, commit kimliği, release diff,
backup, merge/migration, CLI update ve proje metadata refresh salt okunur
incelenmeli; kullanıcı onayı olmadan eşitleme uygulanmamalıdır.

Bu handoff production source, kurulu CLI veya `.krcn` kullanıcı verisini
değiştirme yetkisi vermez.
