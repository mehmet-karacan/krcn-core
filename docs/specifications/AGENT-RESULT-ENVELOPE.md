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

