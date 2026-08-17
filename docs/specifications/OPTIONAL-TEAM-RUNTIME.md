# Opsiyonel Team Runtime

KRCN Core local-first SQLite runtime ile çalışır. Team Runtime bir varsayılan
veya önceki fazların önkoşulu değildir. `team-runtime.assess` yalnız açık
operasyon kanıtını değerlendirir; bağlantı kurmaz, migration planlamaz ve yetki
vermez.

Çok makineli claim, en az iki execution machine, merkezi artifact/HA/tenant/RLS
ihtiyacından biri, migration ve rollback sahipleri ile işletim bütçesi birlikte
yoksa karar `deferred` olur. Hepsi varsa sonuç yalnız
`eligible-for-separate-plan` üretir. PostgreSQL adapter, RLS, HA ve migration
suite'i ayrı exact plan ve onay gerektirir.
