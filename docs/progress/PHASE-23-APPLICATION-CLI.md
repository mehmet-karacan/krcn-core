# Faz 23 application ve CLI yuzeyi

## Tamamlanan kapsam

- `routing.decide` ve `routing.explain` transport-neutral application
  operasyonlari eklendi.
- CLI `krcn routing decide|explain --request-file ...` komutlari eklendi.
- Text cikti JSON yerine okunur tabloyla golge rota, eszamanlilik, reason code,
  comparison ve authority sonucunu gosteriyor.
- CLI, SDK, MCP, Codex, Claude ve OpenCode client kimlikleri ayni route request
  icin ayni karar digest'ini uretiyor.
- `apply`, unknown argument ve noncanonical request fail-closed reddediliyor.

## Kalici sinir

Bu yuzey route karari veya comparison kaydini user-data alanina yazmiyor.
Mevcut execution davranisini degistirmiyor ve yeni authority uretmiyor.
Coordinator shadow entegrasyonu ayri checkpointte bu karari mevcut trace ile
baglayacak.
