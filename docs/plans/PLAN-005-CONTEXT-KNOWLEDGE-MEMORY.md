# PLAN-005 - Context, knowledge ve memory

## Durum

Aktif. Faz 4, tamamlanmış Faz 3 güvenli merge baseline'ı üzerinde başlatıldı.

## Amaç

KRCN Core'un proje ve görev bilgisini modelden, istemciden, sohbet geçmişinden ve compaction davranışından bağımsız biçimde yeniden kurabilmesini sağlamak. Authoritative source, knowledge, memory, state, history ve derived veri birbirinden ayrılacak; context yalnız görev için gerekli, yetkili ve kanıtlanabilir içerikten üretilecek.

## Değişmez sınırlar

- Sohbet geçmişi kalıcı proje hafızası değildir.
- Authoritative source içeriği varsayılan olarak kopyalanmaz; revision ve kanıt taşıyan logical reference ile bağlanır.
- Derived özet, indeks veya embedding authoritative source yerine geçemez.
- Kaynak revision değiştiğinde ona bağlı knowledge ve derived kayıtlar stale kabul edilir.
- Memory yalnız Memory Gate sonucunda ve gerekli kullanıcı onayıyla kalıcılaşır.
- Çıkarım, tekrar eden tercih veya conversation summary kendiliğinden kullanıcı policy'si olamaz.
- Kullanıcının açık kısıtları, örneğin database üzerinde yalnız `SELECT` izni, memory veya context üretimiyle zayıflatılamaz.
- Secret değerleri knowledge, memory, index, context package, evidence veya log içine alınmaz.
- Remote semantic provider varsayılan olarak kapalıdır; disclosure ve oturum onayı olmadan kullanılamaz.
- Context bütçesi yalnız toplam boyutu değil, kaynak güvenilirliğini ve sinyal değerini de dikkate alır.
- Tüm istemciler aynı retrieval, Memory Gate ve context service kurallarını kullanır.
- Canlı kullanıcı verisi ve salt okunur referans kaynakları repository'ye aktarılmaz.

## Bilgi katmanları

1. `authoritative-source`: Gerçeğin dış veya yerel kanonik kaynağına revision-aware referans.
2. `knowledge`: Kaynak ve kanıta bağlı, kullanıcı tarafından korunabilen yapılandırılmış bilgi.
3. `memory`: Açıkça onaylanmış ve yeniden kullanım amacı taşıyan kalıcı kullanıcı bilgisi.
4. `state`: Aktif işin geçici ve yeniden başlatılabilir çalışma durumu.
5. `history`: Karar, işlem ve doğrulama geçmişi; tek başına güncel gerçek değildir.
6. `derived`: Yeniden üretilebilir indeks, embedding, özet, cache ve retrieval yardımcıları.

## Uygulama adımları

### Adım 1 - Faz bağlamı ve bilgi sınıfları

- Faz 3 baseline'ını değişmez giriş noktası olarak bağla.
- Faz 4 sınır ve kabul ölçütlerini tanımla.
- Altı bilgi sınıfını makinece doğrulanabilir sözleşmeye dönüştür.

### Adım 2 - Provenance ve revision-aware kayıt modeli

- Her bilgi kaydı için logical identity, revision, digest, provenance ve evidence sözleşmesi oluştur.
- Superseded, stale ve archived durumlarını tanımla.
- Secret içeriğin kayıt payload'ına girmesini engelle.

### Adım 3 - Authoritative source ve knowledge catalog

- Source binding ile bilgi kaynaklarını logical catalog'a bağla.
- Curated knowledge kayıtlarını kaynak revision ve evidence ile ilişkilendir.
- Kaynak değişiminde bağlı kayıtların stale durumunu deterministic üret.

### Adım 4 - Exact retrieval

- Kimlik, path, başlık, anahtar ve exact text üzerinden deterministic retrieval oluştur.
- Sonuçları authority, revision ve evidence ile sırala.
- Aynı girdide aynı sonuç ve sıra garantisi ver.

### Adım 5 - Dependency retrieval

- Proje, modül, belge, karar, görev ve kaynak ilişkileri için dependency graph oluştur.
- Yön, derinlik, ilişki türü ve bütçe sınırlarını uygula.
- Döngü ve stale edge durumlarını güvenli biçimde ele al.

### Adım 6 - Semantic retrieval

- Semantic query sözleşmesini provider gate arkasına yerleştir.
- Offline ve deterministic baseline davranışını koru.
- Remote embedding veya model kullanımını disclosure ve session approval olmadan başlatma.

### Adım 7 - Context package builder

- Sabit, göreve bağlı ve kalıcı çalışma durumu katmanlarını birleştir.
- Token, character veya byte bütçesini deterministic uygula.
- Her context item için source ref, revision, digest, authority ve truncation kanıtı taşı.

### Adım 8 - Memory Gate

- Memory candidate, review, approval, reject, supersede ve revoke durumlarını tanımla.
- Fact, preference, decision ve reusable procedure türlerini ayır.
- Kullanıcı onayı olmadan durable memory veya aktif policy üretme.

### Adım 9 - Ortak istemci servisleri

- Search, context build, memory propose, memory review ve memory persist işlemlerini ortak application service'e bağla.
- CLI, SDK, MCP, plugin, Codex, Claude ve diğer istemciler için plan parity sağla.

### Adım 10 - Entegrasyon testleri ve kapanış

- Model değişimi, yeni oturum, compaction sonrası devam, stale source, bütçe, policy koruma ve provider kapısı senaryolarını hermetik test et.
- Faz 4 baseline manifestini ve Türkçe kapanış raporunu oluştur.

## Kabul ölçütleri

- Aynı görev context'i farklı istemcilerde aynı kaynak ve kanıtlarla üretilebilmeli.
- Authoritative source değişikliği stale knowledge ve derived kayıtları görünür kılmalı.
- Exact ve dependency retrieval ağ kullanmadan deterministic çalışmalı.
- Semantic retrieval remote provider'a kendiliğinden bağlanmamalı.
- Context package belirlenen bütçeyi aşmamalı ve hangi içeriğin neden seçildiğini göstermeli.
- Secret değerleri context veya memory içinde görünmemeli.
- Conversation summary onaysız durable memory veya policy haline gelmemeli.
- Kullanıcının explicit policy kısıtları bütün context ve memory işlemlerinde korunmalı.
- Model veya istemci değiştiğinde proje bağlamı sohbet geçmişine ihtiyaç duymadan yeniden kurulabilmeli.

## Onay kapıları

Sentetik kayıtlar ve geçici dizinlerde bütün Faz 4 akışı geliştirilebilir. Gerçek user-data içine knowledge veya memory yazmak, mevcut memory kaydını supersede etmek, source içeriğini kopyalamak, remote provider kullanmak veya kullanıcı policy'sini değiştirmek ayrı dry-run ve geçerli kullanıcı onayı gerektirir.
