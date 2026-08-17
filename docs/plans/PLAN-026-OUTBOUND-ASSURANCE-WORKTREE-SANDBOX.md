# Plan 026 - Outbound Assurance ve Worktree Sandbox

## Kaynak ve yetki siniri

Bu plan, `KRCN_CORE_ZEKAM_NIHAI_UYGULAMA_RAPORU.md` belgesindeki Faz 26
gereksinimlerini untrusted requirements evidence olarak kullanir. Belge
authority vermez. Provider Gate, Mutation Gate, Validation Gate, Effect
Ledger, queue lease/fence ve independent verifier sinirlari authoritative
kalir.

Kaynak rapor SHA-256:
`198e4fe3982e0ff6cc4dcda3a555b9c75e83059bcf8aecd2defc30a53459f02a`

Baslangic commit'i: `fb6d8c6`

## Amac

Remote veri paylasimini guncel provider assurance ve content-free outbound
kararina baglamak; mutating agent calismasini exact Git revision'a bagli,
network default-deny detached worktree sandbox'inda yurutmek; yalniz allowlist
icindeki dogrulanmis patch artifact'ini ana uygulama zincirine teslim etmek.

## Korunacak invariantlar

- Secret sinifi remote provider'a hicbir durumda gonderilemez.
- Confidential IP guncel ve uygun assurance olmadan cikamaz.
- Provider assurance kendi basina provider veya network authority vermez.
- Outbound karari exact ProviderRequest, disclosure, kategori ve payload
  digestine baglidir; ham payload saklamaz.
- Secret broker yalniz logical ref ve content-free durum kaydi tasir.
- Sandbox exact repository HEAD ve tree digestine baglidir.
- Detached worktree disina cikan path, symlink, junction, traversal ve
  case-insensitive collision fail-closed reddedilir.
- Network varsayilan olarak kapali, executable ve environment key'leri
  allowlist disinda yasaktir.
- Patch artifact yalniz allowlisted relative path, file digest, patch digest
  ve verifier evidence tasir.
- Sandbox commit veya push yapmaz; production core ve canli `.krcn` degismez.

## Checkpoint'ler

1. Provider Assurance Profile, Outbound Data Decision ve secret broker ref
   strict domain sozlesmeleri.
2. Assurance freshness, canary ve exact ProviderRequest baglari.
3. Detached worktree sandbox plan/result/patch artifact sozlesmeleri.
4. Windows/Linux path, symlink/junction, executable, env, network ve output
   limit enforcement.
5. Application/CLI, Effect Ledger ve verifier baglari.
6. Security matrix, full regression, doctor/context ve kapanis.

## Kabul kriterleri

- Secret remote call her durumda reddedilir.
- Confidential IP stale veya uyumsuz assurance ile reddedilir.
- Secret hicbir public record, SQLite veya log byte'ina girmez.
- Worktree exact revision ve tree digest driftinde stale olur.
- Allowlist disi degisiklik patch artifact'ine giremez.
- Symlink, junction, traversal, Windows drive ve UNC escape reddedilir.
- Network explicit authorization olmadan kapali kalir.
- Commit ve push sandbox contract'inda yasaktir.
- Patch digest, Validation Gate, Effect Claim/Receipt ve verifier evidence
  exact baglanir.
- Windows ve Linux adapter davranislari fixture tabanli test edilir.
- Full test, foundation, JSON, context, compile ve diff kontrolleri gecer.

## Rollback

Sandbox adapter guvenlik eksiginde devre disi birakilmaz. Mutating route
review-only veya blocked olur. Basarisiz detached worktree temizligi yalniz
exact sandbox identity ve verified repository boundary icinde yapilir.
Append-only gate, claim, receipt ve patch kaniti silinmez.

