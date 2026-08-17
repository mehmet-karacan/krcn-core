# Agent Result Envelope

## Amac

Agent Result Envelope v2, direct worker, Generic DAG ve native istemci
sonuclarinin coordinator tarafindan tek bir guvenli sozlesmeyle ele alinmasini
saglar. Envelope bir yetki kaydi degildir; queue lease, mutation approval,
provider authorization veya verifier kararinin yerini almaz.

## Guvenli veri siniri

`schemas/agent-result-envelope.schema.json` ve
`src/krcn_core/agent_result_envelope.py` asagidaki kurallari uygular:

- ham prompt, model output, source content, secret ve fiziksel path tutulmaz;
- kimlikler ve kararlar digest ile baglanir;
- bulgular, riskler, artifact referanslari, evidence referanslari ve effect
  siniflari bounded listeler olarak tasinir;
- `completed`, `partial`, `failed`, `blocked`, `recovery-required` ve
  `abstained` durumlari birbirinden ayrilir;
- `partial` sonuc eksik step kimliklerini acikca tasir ve tamamlanmis sayilmaz;
- failure durumlari serbest metin yerine kategori ve digest ile kaydedilir;
- envelope digest'i tum public alanlari kapsar.

## Rol kurallari

Explorer mutation effect bildiremez. Worker read disi bir effect'i completed
olarak bildirdiginde claim, receipt ve result digest baglari zorunludur.
Verifier yalniz test/evidence artifact siniflarini uretebilir; bagimsiz verifier
kimligini, kapsanan worker step'lerini ve verdict'i tasir.

## Uyumluluk

Eski agent-result ve worker execution kayitlari bu fazda silinmez. Yeni
execution adapterlari v2 envelope uretir; compatibility okuyuculari eski
kayitlari normalize ederek v2 fan-in sinirina tasiyacaktir. Coordinator final
ozeti yalniz dogrulanmis envelope ve receipt verilerinden uretilir.

`src/krcn_core/agent_result_normalizer.py` bu compatibility sinirini uygular:

- direct worker execution v1/v2 kayitlarini yeniden parse eder;
- Generic DAG adapter result v1'i v2 envelope/receipt ciftine yukseltir;
- native istemciden yalniz strict `schemas/native-agent-result.schema.json`
  payloadini kabul eder; serbest metni authoritative sonuc saymaz;
- client/model ozel alanlari core sonuc sozlesmesine sizdirmaz;
- normalization ciftini `schemas/agent-result-normalization.schema.json` ile
  digest-bound hale getirir.

Mevcut worker v1/v2 journal kaydinin icine geriye donuk generalized effect
alani eklenmez. Faz 25 normalizer'i non-read worker etkisini ayri durable Effect
Claim/Receipt ciftleriyle baglar. Journal effect type ve authorizationlari;
claim task, plan, step, queue, attempt, execution identity ve Validation Gate
baglari; receipt terminal sonucu birebir eslesmeden envelope completed olamaz.

Generic DAG ve native structured client adapterlari da ayni kurali uygular.
Yalniz bir claim/receipt kimligi bildirmek yeterli degildir; tam content-free
sozlesmeler parse edilir ve exact scope'a baglanir. Read-only legacy akisi
claim olmadan uyumlu kalir.

## Coordinator fan-in

`src/krcn_core/agent_result_fanin.py` yalniz `caller_role=coordinator` ile
bounded final ozet uretir. Child envelope ve receipt scope'lari birebir
eslesir; duplicate step/attempt, farkli proje/task baglari ve tamper reddedilir.
Eksik veya basarisiz bir step varsa fan-in completed olamaz. Recovery-required
durumu partial sonuc uzerinde onceliklidir.

Fan-in Work Graph completion'i gerceklestirmez ve `completion_authorized=false`
tasir. Yalniz dogrulanmis child envelope/receipt kimliklerini, step
projeksiyonunu ve deterministik receipt aggregate'ini sunar.
