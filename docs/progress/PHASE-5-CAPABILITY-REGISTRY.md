# Faz 5 capability registry

## Sonuç

Agent, skill, tool ve model kayıtlarını revision, digest, capability, yan etki, ownership erişimi, provider modu ve approval tetikleyicileriyle tanımlayan ortak registry oluşturuldu.

## Uygulanan kurallar

1. Her capability kaydı exact revision ve content digest taşır.
2. Registry aktif agent, skill, tool ve model türlerinin tamamını kapsar.
3. Capability seçimi yalnızca açık record id listesiyle yapılır; host veya istemci ortamından örtük kayıt eklenmez.
4. Seçim çıktısı capability kapsamını kanıtlar ancak işlem yetkisi vermez.
5. Planner ve verifier agent kayıtları write etkisi taşıyamaz; agent düzeyinde write yalnız worker rolüne aittir.
6. User-data yazımı `user-data-mutation` approval tetikleyicisi olmadan tanımlanamaz.
7. Network etkisi yalnız remote provider modu ve `remote-provider-use` approval tetikleyicisiyle tanımlanabilir.
8. Registry veya tek kayıt üzerinde digest dışı değişiklik yapılırsa kayıt reddedilir.

## Doğrulama

- Yedi sentetik core capability kaydı başarıyla yüklendi.
- Explicit planner ve intent normalizer seçimi deterministic sonuç üretti.
- Eksik capability, host tarafından uydurulmuş kayıt, planner write etkisi, onaysız user-data yazımı, onaysız remote provider ve digest değişikliği reddedildi.

## Korunan alanlar

Registry yalnız versioned core capability tanımları içerir. Yerel kurulu tool listesi, gerçek model bilgisi, provider credential, secret veya kullanıcı verisi keşfedilmedi ve kaydedilmedi.
