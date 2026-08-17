# Faz 25 recovery ve doctor checkpoint

## Tamamlanan kapsam

- Effect Ledger tum claim, receipt ve reconciliation payloadlarini yeniden
  parse eden content-free doctor raporu uretiyor.
- Claim var, receipt/reconciliation yok durumu recovery-required listesinde.
- Runtime status aktif lease'e bagli claim ile unattended recovery claimini
  ayiriyor.
- Doctor, aktif lease'e bagli olmayan recovery-required claimi saglik hatasi
  olarak gosteriyor.
- Orphan/tampered claim, receipt, reconciliation, SQLite integrity ve foreign
  key sorunlari fail-closed raporlaniyor.
- Queue v1-to-v2 migration'i ayni SQLite transactioninda pre-state digestli
  forward-only migration journal'i yaziyor.
- Yeni non-read enqueue tam Validation Gate olmadan planlanamiyor.
- Governed claim baglanmadan handler execution allowed olmuyor.

## Dogrulama

- Faz 25 ve yakin runtime/application/CLI/doctor hedef paketi: 108/108;
  Windows symlink yetkisi olmayan ortamda 1 skip.

## Sonraki adim

Resmi ag-kapali full regression, repository kontrolleri ve Faz 25 kapanis
kaydi tamamlanacak.
