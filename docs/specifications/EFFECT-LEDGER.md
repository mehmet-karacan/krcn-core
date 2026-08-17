# Generalized Effect Ledger

## Amac

Effect Ledger, `write`, `execute` ve `network` etkilerini gerceklesmeden once
claim ile; sonrasinda tek terminal receipt ile kayda baglar. Belirsiz sonuc
sessiz retry edilmez ve reconciliation kaydiyla siniflandirilir.

## Effect Claim

Claim su degerleri deterministik bir kimlikte birlestirir:

- project, work item, task, plan, step, queue ve attempt;
- execution identity, lease ve fencing token;
- effect type, digest, authorization ve idempotency key;
- mutation plan veya provider request bagi;
- pre-execution Validation Gate ve runtime host digesti.

Claim `effect_performed=false` tasir. Claim kaydi etkinin gerceklestigi veya
yetkili oldugu anlamina gelmez.

## Effect Receipt

Her claim en fazla bir terminal receipt alabilir. Domain durumlari
`completed`, `failed`, `denied`, `timed-out` ve `uncertain` olarak ayrilir.
Completed sonuc exact result digest ister ve yeniden oynatilamaz. Failure
sonuclari yalniz sanitize edilmis kategori/digest tasir. Stale fencing token
reddedilir.

`uncertain` sonucu `reconciliation-required` olmak zorundadir. Receipt
bulunmayan claim recovery-required sayilacak; bu invariant durable ledger
checkpoint'inde uygulanacaktir.

## Reconciliation

Reconciliation sonucu yalniz `effect-confirmed`, `effect-not-applied` veya
`effect-state-unknown` olabilir. Kayit bounded evidence digestleri tasir,
authority vermez ve implicit replay'e izin vermez. Completed receipt tekrar
reconcile edilmez.

## Guvenli veri siniri

Claim, receipt ve reconciliation kayitlari ham prompt/output, source content,
secret, credential veya fiziksel path icermez. Bilinmeyen alanlar ve digest
tamper fail-closed reddedilir.

## Durable exactly-once store

`src/krcn_core/effect_ledger_store.py`, claim kimligi ve idempotency key icin
veritabani uniqueness uygular. Ayni payload replay'i yeni execution hakki
vermez; farkli payload conflict olur. Claim basina yalniz bir terminal receipt
ve bir reconciliation tutulur. Receipt ve reconciliation bulunmayan claim
`recovery-required` olarak raporlanir.

Store `BEGIN IMMEDIATE`, foreign key, full synchronous commit ve explicit
connection close kullanir. Symlink veya junction ancestor altinda veritabani
acmaz. Reconciliation sonrasi gec receipt kabul edilmez; recovery karari
sessiz retry yerine yeni kontrollu bir akisa birakilir.

## Result projection

Worker execution, Generic DAG ve native structured client sonuclari non-read
bir effect'i Agent Result Envelope'a yalniz durable claim ve completed receipt
ciftiyle tasiyabilir. Normalizer effect, authorization, scope, attempt,
execution identity, Validation Gate ve result digestlerini yeniden dogrular.
Workflow Step Receipt ayni gate kimligini provenance icinde korur.
