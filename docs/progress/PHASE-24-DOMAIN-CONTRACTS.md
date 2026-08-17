# Faz 24 domain sozlesmeleri

## Tamamlanan kapsam

- Agent Result Envelope v2 strict builder/parser ve JSON Schema eklendi.
- Workflow Step Receipt strict builder/parser, aggregation ve JSON Schema
  eklendi.
- Worker, verifier ve explorer rol invariantlari tanimlandi.
- Partial, failure ve recovery durumlari completed sonucundan ayrildi.
- Receipt zaman, kullanim, maliyet, provenance ve actor baglari digest ile
  korundu.
- Ham prompt/output, fiziksel path, secret ve bilinmeyen alanlar fail-closed
  reddedildi.
- Envelope ve receipt public payloadlari schema ile karsilikli dogrulandi.

## Yetki siniri

Bu kayitlar execution, mutation, provider, database, lease veya verification
yetkisi vermez. Mevcut gate ve authorization sozlesmeleri aynen korunur.

## Sonraki checkpoint

Receipt'ler append-only durable store'a alinacak; ayni step/attempt icin
idempotent replay ve conflict kontrolleri eklenecek.

