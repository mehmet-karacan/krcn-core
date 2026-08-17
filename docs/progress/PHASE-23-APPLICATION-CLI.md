# Faz 23 application ve CLI yuzeyi

## Tamamlanan kapsam

- `routing.decide` ve `routing.explain` transport-neutral application
  operasyonlari eklendi.
- `routing.record` append-only runtime kaydi icin exact-plan ve idempotent apply
  siniri ekledi.
- CLI `krcn routing decide|explain --request-file ...` komutlari eklendi.
- Text cikti JSON yerine okunur tabloyla golge rota, eszamanlilik, reason code,
  comparison ve authority sonucunu gosteriyor.
- CLI, SDK, MCP, Codex, Claude ve OpenCode client kimlikleri ayni route request
  icin ayni karar digest'ini uretiyor.
- `apply`, unknown argument ve noncanonical request fail-closed reddediliyor.

## Kalici sinir

`decide` ve `explain` salt okunurdur. `record` yalniz exact plan ve verified
runtime mutation authorization ile append-only kanit yazar. Hicbiri mevcut
execution davranisini degistirmez veya yeni authority uretmez.
