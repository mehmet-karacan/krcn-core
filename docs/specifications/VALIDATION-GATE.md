# Validation Gate

## Amac

Validation Gate, `write`, `execute` ve `network` etkilerinden once worker
adimini, yetki kayitlarini, dogrulama konularini ve bagimsiz verifier
kimligini degismez bir sozlesmeye baglar. Gate kendi basina execution,
mutation, provider, database veya completion yetkisi vermez.

## Pre-execution sozlesmesi

`src/krcn_core/validation_gate.py` ve
`schemas/validation-gate.schema.json` su invariantlari uygular:

- project, work item, task plan, worker step ve effect digestleri exact baglanir;
- worker ile verifier execution ve actor kimlikleri farkli olmak zorundadir;
- verifier ayni task ve plan kapsaminda `verifier` rolunde olmalidir;
- tum subject digestleri check kayitlari tarafindan tam ve yalniz bir kez
  kapsanir;
- write etkisi mutation planina, network etkisi provider requestine baglanir;
- bilinmeyen effect, subject, check methodu veya evidence sinifi reddedilir;
- ham prompt, model output, fiziksel path, secret ve serbest kanit icerigi
  tutulmaz;
- gate kimligi tum public alanlari kapsayan deterministik digesttir.

## Post-execution dogrulamasi

`validate_gate_verification` mevcut Task Verification kaydini yeniden parse
etmez veya yetki uretmez. Trusted runtime tarafindan dogrulanmis kaydin gate
ile exact task, plan, worker, verifier, subject, evidence ve covered-step
baglarini denetler. Eksik, basarisiz veya farkli kimlige ait dogrulama
completion icin kullanilamaz.

## Effect Ledger siniri

Validation Gate yalniz precondition kaydidir. Bir etkinin gerceklesmesi Faz 25
Effect Claim, Effect Receipt ve reconciliation kayitlariyla izlenecektir.
Gate kaydi bulunmasi, claim veya receipt olmadan etkinin tamamlandigi anlamina
gelmez.
