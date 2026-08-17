# Faz 28 Team Runtime ihtiyaç kapısı

- Strict policy, assessment ve public schema eklendi.
- Mevcut kanıt profili: tek makine, cross-machine claim yok, enterprise runtime
  ihtiyacı yok, atanmış migration/rollback bütçesi yok.
- Karar: `deferred`; PostgreSQL gerekli değil, provider call 0, migration yetkisi yok.
- Gerçek çok-makine kanıtı oluşursa yalnız ayrı plan açılır; bu karar doğrudan
  database veya altyapı değişikliği yapmaz.
