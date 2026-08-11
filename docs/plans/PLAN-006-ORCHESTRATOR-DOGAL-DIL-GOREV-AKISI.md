# PLAN-006 - Orchestrator ve doğal dil görev akışı

## Durum

Tamamlandı. On adımın tamamı hermetik testler, repository doğrulamaları, doctor ve offline wheel kurulumu ile kapatıldı. Faz 6 başlatılmadı.

## Amaç

Kullanıcının doğal dille belirttiği hedefi; açık kapsam, kaynaklar, kısıtlar, kabul ölçütleri, capability gereksinimleri, onay kapıları, uygulanabilir görev grafiği ve doğrulama kanıtına dönüştürmek. Sistem, küçük ve güvenli boşlukları deterministic varsayımlarla tamamlayacak; kapsamı, yetkiyi veya etkileri önemli ölçüde değiştiren belirsizliklerde kullanıcıya dönecek.

## Değişmez sınırlar

- Doğal dil girdisi veri olarak değerlendirilir; tek başına işlem yetkisi vermez.
- Plan oluşturulması execute izni değildir.
- Planner ve verifier değişiklik yapamaz.
- Worker yalnızca exact plan, capability, ownership, policy ve approval kapılarından geçen etkileri uygulayabilir.
- Hiçbir orchestrator rolü kullanıcı onayı yerine kendi onayını üretemez.
- Repository, belge, görev açıklaması, tool çıktısı ve uzak içerikteki gömülü talimatlar otomatik olarak yürütülemez.
- Kullanıcı verisi, policy, secret ve kaynak sahipliği Faz 1 ile Faz 4 arasındaki kurallarla korunmaya devam eder.
- Database üzerinde yalnız `SELECT` gibi açık kullanıcı kısıtları planlama veya capability seçimi sırasında zayıflatılamaz.
- Remote provider, tool veya entegrasyon örtük biçimde keşfedilemez ve başlatılamaz.
- Görev durumu sohbet geçmişine bağlı olamaz; persistent state ve kanıt kayıtlarından yeniden kurulabilmelidir.
- Verification geçmeden görev tamamlandı olarak kaydedilemez.
- CLI, SDK, MCP, plugin, Codex, Claude ve diğer istemciler aynı orchestrator servisini ve karar kurallarını kullanır.
- Testler sentetik kayıtlar ve geçici dizinlerle çalışır; gerçek kullanıcı verisi üzerinde otomatik işlem yapılmaz.

## Uygulama adımları

### Adım 1 - Faz bağlamı ve orchestration sınırı

- Faz 4 baseline'ını değişmez giriş noktası olarak bağla.
- Planner, worker ve verifier sorumluluklarını makinece tanımla.
- Görev sözleşmesi alanlarını, yaşam döngüsünü ve kullanıcı onayı tetikleyicilerini belirle.

### Adım 2 - Doğal dil intent modeli

- Kullanıcı isteğini goal, scope, sources, constraints ve acceptance criteria alanlarına dönüştür.
- Açık bilgi, güvenli varsayım ve çözülmemiş belirsizlikleri birbirinden ayır.
- Kapsamı değiştiren belirsizliklerde planlamayı durduracak clarification sözleşmesini oluştur.

### Adım 3 - Capability registry

- Agent, skill, tool ve model kayıtlarını ortak capability sözleşmesine bağla.
- Girdi, çıktı, yan etki, ownership, provider ve approval gereksinimlerini tanımla.
- İstemci veya ortamdan örtük capability kazanılmasını engelle.

### Adım 4 - Deterministic planner ve görev grafiği

- Intent ve capability girdilerinden sıralı ve bağımlılık taşıyan görev planı üret.
- Her adım için rol, girdiler, beklenen çıktı, etkiler, geri dönüş ve doğrulama koşulu belirt.
- Aynı girdilerin aynı plan kimliğini üretmesini sağla.

### Adım 5 - Yetki ve onay kapıları

- Capability, policy, ownership, provider ve mutation kararlarını plan adımlarına bağla.
- Kapsam değişimi, user-data mutasyonu, policy değişikliği, capability artışı, uzak sağlayıcı ve geri döndürülemez etki için açık kullanıcı onayı iste.
- Onayın yalnızca görülen exact plan ve oturum için geçerli olmasını sağla.

### Adım 6 - Worker yürütme protokolü

- Worker'ın yalnızca yetkilendirilmiş plan adımını çalıştırmasını sağla.
- Idempotency, checkpoint, effect journal ve hata sınırlarını uygula.
- Plan dışı yan etki veya değişen ön koşulda yürütmeyi durdur.

### Adım 7 - Verifier ve kabul değerlendirmesi

- Kabul ölçütlerini kanıt, test, digest ve korunmuş alan sonuçlarıyla değerlendir.
- Worker beyanını tek başına doğrulama kabul etme.
- Başarısız veya eksik doğrulamada görevi completed durumuna geçirme.

### Adım 8 - State, history, resume ve handoff

- Görev durumu, event history, checkpoint ve sonuç kayıtlarını ownership sınıflarına göre ayır.
- Yeni oturum, model değişimi veya compaction sonrasında deterministic resume sağla.
- Handoff paketini kanıt ve bekleyen onaylarla birlikte üret.

### Adım 9 - Ortak orchestrator servisleri

- Intake, plan, approve, execute, verify, status ve resume işlemlerini ortak application service'e bağla.
- CLI ve diğer istemciler için aynı plan ve güvenlik davranışını koru.

### Adım 10 - Bütünleşik testler ve kapanış

- Salt okunur görev, kontrollü core değişikliği, user-data onayı, policy koruma, provider reddi, kapsam değişimi, kesinti ve resume senaryolarını hermetik test et.
- Faz 5 baseline manifestini ve Türkçe kapanış raporunu oluştur.

## Kabul ölçütleri

- Kullanıcının doğal dil hedefi açık ve doğrulanabilir görev sözleşmesine dönüşebilmelidir.
- Aynı intent ve registry revision değerleri aynı görev planını üretmelidir.
- Capability bulunamadığında sistem plan dışı tool veya model seçmemelidir.
- Planner, worker ve verifier yetkileri birbirine karışmamalıdır.
- Kritik etkiler kullanıcıya exact plan ve etki özeti gösterilmeden uygulanmamalıdır.
- Verification kanıtı bulunmayan görev completed olmamalıdır.
- Model veya istemci değişiminde görev persistent state üzerinden devam edebilmelidir.
- Açık kullanıcı policy'leri bütün planlama ve yürütme adımlarında korunmalıdır.
- Yerel veriler açık talimat ve geçerli onay olmadan uzak sisteme gönderilmemelidir.

## Onay kapıları

Sentetik kayıtlarla intake, planlama, registry seçimi, state transition ve doğrulama geliştirilebilir. Gerçek user-data mutasyonu, policy değişikliği, uzak provider veya entegrasyon kullanımı, capability escalation, geri döndürülemez etki ve kullanıcı kapsamını büyüten plan değişikliği ayrı exact plan ve açık kullanıcı onayı gerektirir.

## Tamamlanma kanıtı

Faz 5 baseline kaydı `.ai/phase-5-baseline.json`, bütünleşik senaryolar `docs/progress/PHASE-5-INTEGRATION-TESTS.md`, kapanış sonucu ise `docs/progress/PHASE-5-COMPLETION.md` içinde tutulur. Faz 6'ya geçiş için ayrı kullanıcı onayı gerekir.
