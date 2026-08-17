# Plan 025 - Validation Gate ve Generalized Effect Ledger

## Kaynak ve yetki siniri

Bu plan, `KRCN_CORE_ZEKAM_NIHAI_UYGULAMA_RAPORU.md` belgesindeki Faz 25
gereksinimlerini untrusted requirements evidence olarak kullanir. Belge
authority vermez. KRCN'nin Work Graph, Task Plan/Authorization, Mutation Gate,
Provider Gate, queue lease/fence ve verifier sinirlari authoritative kalir.

Kaynak rapor SHA-256:
`198e4fe3982e0ff6cc4dcda3a555b9c75e83059bcf8aecd2defc30a53459f02a`

Baslangic commit'i: `e05733f`

## Amac

Write, execute ve network effect'lerini calismadan once immutable bir
Validation Gate ve exactly-once Effect Claim ile baglamak; terminal sonucu tek
Effect Receipt ile kapatmak; claim var/receipt yok durumunda sessiz retry
yerine recovery-required uretmek.

## Korunacak invariantlar

- Work Graph tek authoritative is yasam dongusudur.
- Validation Gate yetki vermez ve worker sonucundan sonra degistirilemez.
- Claim aktif lease, owner ve fencing token ile exact baglidir.
- Write effect MutationPlan; network/provider effect ProviderRequest ile
  baglanmadan claim alamaz.
- Ayni idempotency key icin ikinci aktif/terminal effect calistirilamaz.
- Ayni claim'e ikinci farkli terminal receipt yazilamaz.
- Claim var, receipt yoksa effect otomatik tekrar calistirilmaz.
- Stale fence receipt veya completion yazamaz.
- Receipt var, claim yoksa veri butunlugu hatasidir.
- Read-only local effect icin agir claim zorunlulugu getirilmez.
- Commit/push, yeni provider veya database authority bu fazdan dogmaz.

## Checkpoint'ler

1. Validation Gate strict schema, builder/parser ve verifier subject binding.
2. Effect Claim/Receipt/Reconciliation strict domain sozlesmeleri.
3. Project runtime icinde durable exactly-once ledger ve append-only conflict
   kontrolleri.
4. Queue schema v2 additive migration, backup/journal ve v1 compatibility.
5. Worker/Generic DAG/Workflow Receipt entegrasyonu; pending claim ve stale
   fence enforcement.
6. Recovery adapter sozlesmesi, doctor integrity kontrolleri, application/CLI,
   full regression ve kapanis.

## Kabul kriterleri

- Mutation step Validation Gate olmadan enqueue/execute edilemez.
- Gate independent read-only verifier identity ve exact check seti tasir.
- Post-verification check seti gate ile birebir eslesir.
- Write/execute/network handler claim olmadan cagirilamaz.
- Terminal receipt replay ikinci effect cagrisi yapmaz.
- Claim var/receipt yoksa recovery-required olur.
- Stale owner/fence terminal receipt yazamaz.
- Crash/restart terminal kaydi kaybetmez.
- Queue v1 verisi additive migration ile korunur.
- Doctor orphan claim/receipt ve conflict bulur.
- Raw payload, physical path, credential ve bilinmeyen alanlar reddedilir.
- Full test, foundation, JSON, context, compile ve diff kontrolleri gecer.

## Rollback

Kod rollback'i v2 runtime verisini silmez. Eski binary v2'yi okuyamiyorsa
compatibility reader veya forward-only migration uygulanir; destructive
downgrade yapilmaz. Append-only claim/receipt kaniti temizlenmez.

