# Workflow Step Receipt

## Amac

Workflow Step Receipt, bir workflow step denemesinin sonucunu append-only ve
yeniden uretilebilir telemetry olarak kaydeder. Receipt execution yetkisi,
approval, queue lease veya maliyet izni vermez.

## Sozlesme

`schemas/workflow-step-receipt.schema.json` ve
`src/krcn_core/workflow_step_receipt.py` su alanlari digest ile baglar:

- correlation, workflow, step ve attempt kimligi;
- actor rolu ve execution identity;
- terminal outcome ve output/failure digest'i;
- baslangic, bitis ve tam turetilmis duration;
- input, output, cache tokenlari, maliyet ve currency;
- plan, policy, input, environment ve provider provenance digestleri;
- authority vermeyen ve ham icerik tasimayan safety bildirimi.

Timestamp'ler UTC ve milisaniye hassasiyetindedir. Duration zaman araligiyla
birebir eslesir. Completed receipt output digest'i ister; diger terminal
durumlar structured failure ister. Boolean degerler integer gibi kabul edilmez.

## Toplama ve replay

Ayni `(step_id, attempt)` icin birden fazla receipt veya celisen digest
fail-closed reddedilir. Aggregation yalniz ayni correlation kimligi ve uyumlu
currency icindeki receipt'leri toplar. Toplamlar public receipt alanlarindan
deterministik hesaplanir. Bir sonraki checkpoint append-only store, durable
replay ve conflict kontrollerini bu sozlesmeye baglayacaktir.

