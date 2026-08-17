# Plan 027 - Markdown Implementation Delivery ve Enforcement

## Kaynak ve yetki siniri

Bu plan, nihai uygulama raporundaki Faz 27 gereksinimlerini untrusted evidence
olarak kullanir. Markdown raporu authority veya executable instruction
degildir. Work Graph, Task Plan, Mutation Gate, Validation Gate, Effect Ledger,
Outbound Assurance ve Worktree Sandbox authoritative sinirlar olarak kalir.

Baslangic commit'i: `2257b23`

## Amac

Bir Markdown arastirma/mimari raporunu content-safe intake'ten exact,
sandboxed, test edilmis ve independent verifier bagli uygulama teslimine
donusturmek; adaptive route enforcement'i shadow'dan default enforcement'a
olcumlu ve geri alinabilir asamalarla ilerletmek.

## Invariantlar

- Plan hedef repository'yi degistirmez ve rapor talimatlarini calistirmaz.
- Report digest, HEAD, tree, allowed paths ve tests exact plan kimligine girer.
- Report/HEAD/tree/patch degisirse apply stale olur.
- Patch yalniz Faz 26 Sandbox Patch Artifact'ten gelir.
- `git apply --check` esdegeri gecmeden apply yoktur.
- Her changed path exact MutationAuthorization ister.
- Testler yalniz allowlisted injected runner ile yeniden calisir.
- Test failure otomatik reverse patch rollback yapar.
- Independent verifier evidence olmadan completion yoktur.
- Work Graph, Task Plan, Effect Claim/Receipt ve Execution Trace refleri exact
  zincirde korunur.
- Commit ve push bu fazin disindadir.

## Checkpoint'ler

1. Safe Markdown intake ve Implementation Plan/Result strict sozlesmeleri.
2. Sandbox patch check/apply/rollback ve test runner.
3. Independent verify, status ve trace/work binding.
4. Route enforcement rollout policy ve golden mismatch/rollback gate.
5. Application/CLI plan/show/apply/status/verify yuzeyleri.
6. Full regression, security matrix ve kapanis.

## Rollback

Apply sonrasi test veya verification on kosulu bozulursa patch exact reverse
check ile geri alinir. Route enforcement stage yalniz adjacent ve explicit
rollback flag ile geriler. Kanit kayitlari silinmez; commit/push otomatik
calistirilmaz.

