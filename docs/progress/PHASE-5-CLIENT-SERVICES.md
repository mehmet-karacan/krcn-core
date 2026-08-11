# Faz 5 ortak orchestrator servisi ve istemciler

## Amaç

Intent, plan, authorization, worker, verifier, state ve resume işlemlerini tek bir transport-neutral uygulama servisi üzerinden sunmak; istemcilerin güvenlik ve karar kurallarını çoğaltmasını engellemek.

## Tamamlananlar

1. Ortak uygulama servisine sekiz orchestrator operasyonu eklendi: `intent`, `plan`, `authorize`, `start`, `execute`, `verify`, `status` ve `resume`.
2. Intent operation ham talebi kalıcılaştırmadan typed intent üretti.
3. Plan operation repository capability registry kaydını yeniden yükleyip exact selection ve task plan üretti.
4. Authorization operation kullanıcı politikalarını yalnız yerel policy alanından yükledi ve mevcut güvenlik kapılarını kullandı.
5. Start, execute ve verify durum değişiklikleri `apply` ile exact task plan kimliği olmadan çalışmadı.
6. Worker ve verifier handler registry nesneleri uygulama servisine açıkça enjekte edildi; istemci veya host keşfi yapılmadı.
7. Execute operation checkpoint, journal, state event ve handoff kayıtlarını ortak state store üzerinden güncelledi.
8. Verify operation yalnız persisted worker kanıtlarını kullandı ve completion kararını ortak verifier sonucuna bağladı.
9. Status ve resume işlemleri ham yerel kayıt veya sohbet içeriği döndürmeden güvenli özet üretti.
10. CLI için JSON request alan ince `orchestrator` adaptörü eklendi.

## İstemci eşitliği

CLI, SDK, MCP, plugin, Codex, Claude ve daha sonra eklenecek istemciler aynı `KrcnApplicationService` operasyonlarını çağırır. `client_kind` planı, policy kararını, approval gereksinimini, handler kapsamını veya completion sonucunu değiştirmez. Yeni bir istemci yalnız taşıma ve sunum katmanı ekler.

## CLI operasyonları

- `krcn orchestrator intent`
- `krcn orchestrator plan`
- `krcn orchestrator authorize`
- `krcn orchestrator start`
- `krcn orchestrator execute`
- `krcn orchestrator verify`
- `krcn orchestrator status`
- `krcn orchestrator resume`

Her operasyon girdisini `--request-file` ile JSON olarak alır. State değiştiren operasyonlar ayrıca `--apply` ve `--expected-plan` ister. Handler çalıştıran operasyonlarda handler'ın uygulama servisine önceden açıkça kaydedilmiş olması gerekir.

## Doğrulama

- Yedi farklı istemci türü aynı deterministic task planı aldı.
- SDK ile authorization, plugin ile start, Codex ile execute, Claude ile verify ve MCP ile resume aynı state zincirinde çalıştı.
- CLI ile üretilen plan, doğrudan servis planıyla aynı kimliği taşıdı.
- Intent servis yanıtında ham kullanıcı talebi tutulmadı.
- Şemalar ve tüm depo testleri doğrulandı.

## Sonraki adım

Faz 5 uçtan uca güvenlik senaryolarını genişletmek, offline wheel doğrulamasını çalıştırmak ve phase baseline ile kapanış belgelerini üretmek.
