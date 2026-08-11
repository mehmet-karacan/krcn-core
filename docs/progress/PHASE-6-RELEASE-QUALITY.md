# Faz 6 release ve kalite kapıları

## Sonuç

Faz 6 release uygunluğu makinece doğrulanan profile, cross-platform CI matrisine, doctor kontrolüne ve offline wheel smoke testine bağlandı.

## Zorunlu kapılar

- Repository verification.
- Tam hermetik test paketi.
- Doctor.
- Offline wheel build, install ve portability import testi.
- Portable backup ve restore.
- Dış proje no-copy garantisi.
- Kullanıcı policy koruması.
- Rollback hazırlığı.

## Platform matrisi

GitHub Actions workflow Windows ve macOS üzerinde Python 3.11 ve 3.13 ile çalışacak şekilde tanımlandı. Testler yalnız repository içeriğini ve sentetik geçici dizinleri kullanır.

## Paket doğrulaması

Dependency-free build backend wheel üretir. Wheel network kapalıyken kurulur ve `project.rebind`, `portability.backup`, `portability.restore` ile `portability.migrate-repo-local` operation değerlerini ortak application service içinde sunar.

## Rollback kanıtı

- Core deployment doğrulama hatasında otomatik rollback kullanır.
- Portable restore doğrulanmamış staging alanını hedef olarak yayınlamaz.
- Repo-local migration eski `.krcn` kaynağını korur.

