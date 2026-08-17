# Faz 26 worktree sandbox checkpoint

## Tamamlanan kapsam

- Windows, Linux ve macOS icin ortak strict Sandbox Host Profile eklendi.
- Eksik network/path/env/junction/commit-push enforcement execution'i blocked
  yapiyor.
- Sandbox plani exact Git HEAD/tree, Validation Gate, Effect Claim, runtime
  MutationPlan, path/executable/env allowlist ve network kararina baglandi.
- Gercek `git worktree add --detach` ve exact kimlik dogrulamasi eklendi.
- Changed path allowlist, traversal, drive, UNC, case collision, symlink,
  junction, commit drift ve stale source fail-closed.
- Untracked dosyalar patch'e dahil ediliyor; patch boyutu exact planla sinirli.
- Public patch artifact patch byte'i veya fiziksel path tasimiyor; receipt ve
  verifier evidence digestlerine exact bagli.
- Sandbox commit/push yapmiyor ve arbitrary subprocess API sunmuyor.

## Dogrulama

- Worktree sandbox hedef paketi: 6/6 gecti.
- Windows ve Linux host profilleri ayni enforcement sozlesmesiyle dogrulandi.
- Gercek gecici Git repository/worktree create, patch collect ve cleanup testi
  gecti.

## Sonraki adim

Outbound ve sandbox kararlarini application/CLI, runtime effect ve doctor
yuzeylerine bagla.

