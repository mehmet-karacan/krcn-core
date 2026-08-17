# Faz 26 kickoff

## Baslangic

Faz 25 `fb6d8c6` commit'inde kapandi. Kullanici Faz 26, Faz 27 ve gercek
ihtiyac kapisina bagli Faz 28'in `krcn-core-dev` uzerinde tamamlanmasini;
production `krcn-core` esitlemesi oncesinde durulmasini onayladi.

## Ilk kararlar

- Faz 26 yeni authority uretmeyecek; mevcut Provider, Mutation, Validation ve
  Effect Ledger zincirlerine baglanacak.
- Remote payload icerigi authoritative kayda alinmayacak.
- Sandbox detached Git worktree kullanacak ve ana worktree'ye yazmayacak.
- Network, executable, environment ve changed path izinleri exact planin
  parcasi olacak.
- Commit/push sandbox icinde yasak kalacak.
- Production core, kurulu CLI ve canli `.krcn` bu faz boyunca korunacak.

## Sonraki adim

Provider assurance ve outbound decision domain sozlesmelerini uygula.

