# Plan 028 - Opsiyonel Team Runtime ihtiyaç kapısı

Faz 28, Faz 23-27 için önkoşul değildir. PostgreSQL, RLS, merkezi artifact
store, HA ve multi-machine runtime yalnız doğrulanmış operasyon ihtiyacı varsa
eklenir.

## Kapı

- Birden fazla gerçek execution machine veya cross-machine claim gereksinimi.
- Merkezi artifact store ya da tenant isolation/RLS gereksinimi.
- Ölçülmüş availability hedefinin local SQLite ile karşılanamaması.
- Migration ve rollback sahibi ile işletim bütçesi.

Kanıt yoksa karar `deferred` olur. Bu, eksik implementation değil; gereksiz
dağıtık sistem maliyetini önleyen tamamlanmış mimari karardır.
