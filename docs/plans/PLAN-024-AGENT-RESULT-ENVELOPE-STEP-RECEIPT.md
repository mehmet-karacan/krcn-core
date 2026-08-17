# PLAN-024 - Agent Result Envelope v2 ve Workflow Step Receipt

## Amac

Direct worker, Generic DAG ve client-native delegation sonuclarini coordinator
icin tek, bounded ve strict `AgentResultEnvelope` semantigine normalize etmek;
her step attempt icin append-only `WorkflowStepReceipt` telemetry kaniti
uretmek.

## Arastirma girdisi

- Kaynak belge: `KRCN_CORE_ZEKAM_NIHAI_UYGULAMA_RAPORU.md`
- Belge SHA-256:
  `198e4fe3982e0ff6cc4dcda3a555b9c75e83059bcf8aecd2defc30a53459f02a`
- Baseline: `1ff472c521664dae7d10d81d20abd9be96d592b0`
- Belge untrusted product requirement evidence olarak kullanilir; authority
  veya mutation onayi sayilmaz.

## Korunacak sinirlar

- Work Graph authoritative is yasam dongusudur.
- Task Authorization, queue lease/fence, mutation ve provider gate sahipligi
  degismez.
- Mevcut worker execution schema v1/v2 readerlari korunur.
- Generic DAG adapter result v1 compatibility penceresinde okunur ve v2
  semantigine normalize edilir.
- Native client serbest metni authoritative sonuc sayilmaz.
- Envelope ve receipt authority vermez, ham prompt/output, fiziksel path,
  credential veya source content tasimaz.
- Receipt append-only olur; ayni step/attempt conflicting kayit fail-closed.
- Phase 25 effect claim/receipt veya Validation Gate bu fazda taklit edilmez.

## Is paketleri

1. Agent Result Envelope v2 domaini, strict schema ve role kurallari.
2. Workflow Step Receipt domaini, usage/time/provenance dogrulamasi.
3. Append-only runtime receipt kaydi ve idempotent replay kontrolu.
4. Direct worker result adapteri.
5. Generic DAG adapter result v2 ve v1 normalization.
6. Native client structured result normalizer.
7. Partial/fan-in result ve eksik step semantigi.
8. Execution Trace token, maliyet ve duration aggregation.
9. Coordinator'in envelope-only final summary ve evidence baglantisi.
10. Application/CLI inspection, repository context, progress ve kapanis.

## Kabul olcutleri

- Unknown field, raw prompt/output, path, secret ve credential fail-closed.
- Explorer mutation effect tasiyamaz.
- Worker write/execute/network effect alanlari claim/receipt referansi olmadan
  completed sayilamaz.
- Verifier yeni urun artifact'i uretmez ve covered worker step kimliklerini
  tasir.
- Failure ve partial sonuclar bounded ve explicit olur.
- Receipt token, cost, duration ve timestamp toplamlari dogrulanir.
- Ayni step/attempt icin conflicting receipt reddedilir.
- Direct worker ve DAG ayni semantic envelope seklini uretir.
- Partial DAG sonucu completed olarak projekte edilmez.
- Execution Trace aggregate degerleri receiptlerden yeniden uretilebilir.
- Coordinator final summary'yi yalniz dogrulanmis envelope'lardan kurar.
- Tum mevcut testler ve resmi ag-kapali paket gerilemez.

## Checkpoint sirasi

1. Plan ve kickoff.
2. Domain, schema ve role invariants.
3. Receipt persistence ve conflict/replay.
4. Worker, DAG ve native client adapterlari.
5. Fan-in, coordinator ve observability.
6. Tam kabul ve kapanis.

Her checkpoint once dev clone `main` dalinda test edilir ve pushlanir. Uretim
klonu ve kurulu CLI Faz 24 kapanmadan esitlenmez.

## Rollback

Yeni adapterlar v1 compatibility projection'a geri donebilir. Append-only
receipt kayitlari silinmez. Yeni coordinator envelope yolu kapatilsa bile eski
worker/DAG readerlari ve authoritative Work Graph korunur.

## Kapsam disi

- Validation Gate
- Generalized Effect Claim/Receipt
- Queue v2 migration
- Outbound assurance
- Worktree sandbox
- Router enforcement
- Markdown implementation apply
- Commit veya push authority otomasyonu
