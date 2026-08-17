# ADR-025-001: Pre-execution Validation Gate

## Durum

Kabul edildi.

## Karar

Write, execute ve network etkisi tasiyan yeni runtime adimlari enqueue
edilmeden once immutable bir Validation Gate tasir. Gate project, work item,
task, plan, step, effect, authorization, subject/check matrisi ve bagimsiz
verifier execution identity'sini deterministik digest ile baglar.

Gate yetki vermez. MutationPlan, ProviderRequest, queue lease/fence ve
post-execution Task Verification ayri authoritative sinirlar olarak kalir.
Task Verification ancak gate ile exact subject, evidence, worker ve verifier
baglari eslesirse completion kaniti olabilir.

## Sonuclar

- Worker sonucundan sonra basari olcutu degistirilemez.
- Read-only eski queue adimlari geriye donuk gate uydurmadan korunur.
- Yeni non-read enqueue tam gate payloadini dogrulamak zorundadir.
- Gate kaydi tek basina handler execution veya completion baslatamaz.
