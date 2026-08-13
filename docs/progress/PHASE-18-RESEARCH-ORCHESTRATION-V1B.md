# Faz 18 Research Orchestration V1B

## Sonuç

Research Orchestration V1B, V1A'nın kullanıcı aracılı araştırma akışını gerçek
yerel alt ajan yürütme sınırıyla tamamladı. Ana ajan koordinatör olarak kalır.
Araştırmacı ve mimari inceleme ajanları bağımsız ve paralel çalışabilir. Eleştirmen,
sentezleyici ve atıf doğrulayıcı bağımlılık sırasına göre yürür.

## Tamamlananlar

- OpenCode, Codex CLI ve Claude CLI için güvenli yürütme politikası tanımlandı.
- İstemci çalıştırılabilirliği salt okunur çözümleme ve sağlık kontrolüyle ölçülür.
- Prompt yalnız standart girdiden iletilir. Shell komut dizgesi üretilmez.
- Süre aşımı, çıktı sınırı, süreç ağacı sonlandırma ve iptal desteği eklendi.
- Beş araştırma rolü Agent Runtime Queue lease ve fencing kurallarıyla bağlandı.
- İlk iki bağımsız rol en fazla iki eş zamanlı ajanla çalışabilir.
- Worker ve verifier kimliklerinin birbirinden farklı olması zorunludur.
- Exact-plan, kullanıcı onayı ve istemci delegasyon kararı korunur.
- Her rol için worker kimliği, istemci yürütme isteği ve sağlayıcı açıklaması exact
  plana bağlandı.
- Uygulama servisi OpenCode, Codex CLI ve Claude CLI için varsayılan runtime
  adaptörlerini bu açık atamalardan kurar. Host keşfi yapmaz.
- OpenCode, Codex CLI ve Claude CLI yollarına istemciye özgü salt okunur sınırlar
  eklendi.
- Adaptör enjeksiyonu sağlayıcı yetkisi değildir. Enjekte edilen ve varsayılan
  yollar aynı exact Provider Gate kontrolünden geçer.
- Sağlayıcı yetkisi yoksa veya dispatch isteğiyle eşleşmiyorsa çalışma engellenir.
- Serbest metin araştırma yanıtı tamamlanma sayılmaz. Yalnız doğrulanan
  `research-agent-result-v1` JSON zarfı kabul edilir.
- Eleştirmen, sentezleyici ve atıf doğrulayıcı kendilerinden önceki doğrulanmış
  sonuçların sınırlı ve canonical bağlam projeksiyonunu alır.
- Uzun model çağrılarında lease süresi periyodik heartbeat ile yenilenir.
- Manuel araştırma çıktıları native tamamlanma olarak kabul edilmez.
- İptal yalnız çalışan uygulama süreciyle sınırlıdır.
- Ayrı bir CLI süreci, başka CLI sürecinde çalışan dispatch işlemini iptal edemez.
- Yeniden başlatma sonrası sahte devam yerine yeni exact dispatch planı ve yeni
  `research_id` istenir.
- Gemini opsiyoneldir; API anahtarı, ek maliyet veya zorunlu bağımlılık oluşturmaz.
- `gpu-fusion` sahte process runner pilotunda varsayılan adapter factory ile tüm
  beş rol tamamlandı ve kuyruk kanıtı doğrulandı.

## Sağlanan operasyonlar

- `research availability`
- `research dispatch`
- `research cancel`
- `research runtime-status`
- `research resume`

## Korunan sınırlar

- Gerçek sağlayıcı veya model çağrısı testlerde yapılmadı.
- İstemci yetenek bildirimi yetki vermez.
- Sağlayıcı seçimi veri aktarımı veya uzaktan çağrı yetkisi vermez.
- Proje kaynakları kopyalanmaz ve değiştirilmez.
- Ham araştırma çıktısı otomatik olarak bilgi, bellek veya politika olmaz.
- Yeni vektör veri tabanı, RAG veya graph veritabanı eklenmedi.

## Doğrulama

- V1B application smoke testleri: başarılı
- Research execution ve runtime birim testleri: başarılı
- Repository foundation ve JSON doğrulaması: başarılı
- Tam regresyon: başarılı

## Devam sınırı

V1B ürün temelini tamamlar. Gerçek provider çağrısı ancak kullanıcının açık rol
atamaları, exact planı ve sağlayıcı onayıyla çalışabilir. Aynı `research_id` ile
kalıcı resume ve süreçler arası cancel desteklenmez; bu sınırlar kullanıcıya açık
biçimde `unavailable` veya yeni kimlik gereksinimi olarak bildirilir.
