# Faz 25 durable Effect Ledger checkpoint

## Tamamlanan kapsam

- Effect Claim, Receipt ve Reconciliation icin durable SQLite store eklendi.
- Idempotency key veritabani seviyesinde unique yapildi.
- Ayni claim replay'i no-op ve `execution_allowed=false` donuyor.
- Ayni idempotency key altinda farkli claim fail-closed reddediliyor.
- Claim basina tek terminal receipt ve tek reconciliation zorunlu.
- Receipt bulunmayan claim recovery-required olarak listeleniyor.
- Reconciliation sonrasi gec terminal receipt reddediliyor.
- Transaction rollback, foreign key ve SQLite integrity kontrolleri eklendi.
- Windows dahil tum SQLite baglantilari explicit commit/rollback/close ile
  sinirlandi.
- Symlink ve junction ancestor veritabani hedefleri reddedildi.

## Dogrulama

- Durable ledger testleri: 6/6; symlink yetkisi olmayan Windows ortaminda 1
  koruma testi skip.

## Sonraki checkpoint

Agent Runtime Queue v2'ye additive effect claim/receipt baglari eklenecek.
Mevcut queue v1 kayitlari korunacak ve effect kullanmayan adimlar uyumlu
okunmaya devam edecek.
