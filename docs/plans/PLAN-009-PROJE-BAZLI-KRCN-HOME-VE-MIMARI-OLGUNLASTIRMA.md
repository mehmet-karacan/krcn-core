# PLAN-009 - Proje bazlı KRCN_HOME ve mimari olgunlaştırma

## Durum

Aktif. Faz 8, Mehmet KARACAN'ın açık isteğiyle başlatıldı.

## Amaç

KRCN Core'u mevcut Faz 7 baseline davranışını bozmadan üretim koşullarına hazırlamak ve proje kapsamındaki varsayılan kullanıcı çalışma alanını `<proje-kökü>/.krcn` olarak tanımlamak.

Kullanıcı ilk kurulumda önerilen yerel konumu görecek, bu dizinin Git'e veya uzak servislere gönderilmeyeceği konusunda bilgilendirilecek ve varsayılan konumu kullanma, farklı bir konum seçme veya işlemi iptal etme seçeneklerinden birini belirleyebilecek.

## Değişmez sınırlar

- Proje kaynak dosyaları `.krcn` içine veya KRCN Core repository'sine kopyalanmaz.
- Proje kapsamındaki varsayılan KRCN kullanıcı evi `<proje-kökü>/.krcn` olur.
- İlk initialization işlemi konumu göstermeden ve kullanıcı kararı almadan dizin oluşturmaz.
- Açık `data_root` veya `KRCN_HOME` seçimi geriye dönük uyumluluk için korunur.
- `.krcn` Git tarafından izlenmez ve hiçbir uzak servise otomatik gönderilmez.
- Git clone işleminin `.krcn` verisini geri getirmediği kullanıcıya açıkça bildirilir.
- Source binding varsayılan olarak salt okunur kalır. Yalnız KRCN tarafından yönetilen `.krcn` kontrol alanı bu sınırdan ayrılır.
- Discovery ve source identity hesapları `.krcn` içeriğini kaynak proje içeriği saymaz.
- Kullanıcı policy'leri, özellikle veritabanı `select` kısıtları, core güncellemesi veya adapter değişikliğiyle zayıflatılmaz.
- Secret değerleri Git'e, loglara, normal backup paketine veya proje metadata kayıtlarına yazılmaz.
- Her user-data değişikliği dry-run, exact plan, onay ve doğrulama kapılarından geçer.
- Büyük yeniden yazım yapılmaz. Her adım mevcut baseline üzerinde küçük, test edilebilir ve geri alınabilir bir değişiklik olur.

## Uygulama adımları

### Adım 1 - Araştırma, kapsam ve mimari karar

Araştırma raporlarındaki bulguları güncel repository üzerinde doğrula. Proje bazlı KRCN_HOME kararını ADR, teknik sınır ve Faz 8 başlangıç kaydıyla sabitle.

### Adım 2 - Proje çalışma alanı çözümleme

Proje kökünü güvenli biçimde çözümle. Açık `data_root`, daha önce seçilmiş proje konumu ve `<proje-kökü>/.krcn` önerisini deterministik öncelik sırasıyla ele alan salt okunur resolution planı üret.

### Adım 3 - Güvenli initialization ve Git koruması

Varsayılan veya kullanıcı tarafından seçilen konum için exact initialization planı üret. `.krcn` Git tarafından izleniyorsa fail-closed davran; takip edilen `.gitignore` dosyasını sessizce değiştirmeden yerel dışlama seçeneği sun.

### Adım 4 - Proje öğrenme ve istemci entegrasyonu

`project.learn`, CLI, SDK, MCP, plugin, Codex ve Claude akışlarını aynı çalışma alanı seçim sözleşmesine bağla. Kullanıcıya teknik kimlik sormadan konum seçimini plan içinde göster.

### Adım 5 - Taşınabilirlik, migration ve kurtarma

Merkezi veya eski repository-local yerleşimleri veri kaybı olmadan proje bazlı çalışma alanına taşıyabilecek inspect, backup, exact-plan, apply, verify ve rollback akışını oluştur. Git clone ile backup/restore arasındaki farkı belgeleyip temiz makine tatbikatıyla doğrula.

### Adım 6 - Veri bütünlüğü ve güncellik

Deployment durum algılama hatasını, eş zamanlı kayıt yazma yarışını ve memory staleness boşluğunu düzelt. Başarısız rollback, bozuk backup ve yarım migration senaryolarını regresyon testleriyle koru.

### Adım 7 - Entegrasyon ve secret çalışma katmanı

Adapter, worker, verifier ve secret provider kayıt sınırlarını ortaklaştır. En az bir gerçek salt okunur referans akışını policy, capability ve secret reference kapılarından geçir. Harici proje veya veritabanı içeriğini KRCN içine kopyalama.

### Adım 8 - Retrieval kalitesi ve ölçek

Semantic retrieval için ölçülebilir bir değerlendirme seti oluştur. Exact, dependency ve semantic sonuçlarını ortak ve açıklanabilir bir sıralama akışında birleştir. Büyük proje ve büyük bilgi kataloğu performansını ölçmeden yeni indeks teknolojisi seçme.

### Adım 9 - Kalite, gözlemlenebilirlik ve kullanıcı deneyimi

Linux CI, başlangıç coverage ölçümü, deterministik düşmanca testler, runtime doctor kontrolleri, okunabilir orchestration zaman çizelgesi, yönlendirici hata mesajları ve uçtan uca quickstart ekle.

### Adım 10 - Bütünleşik doğrulama ve kapanış

Proje içi ve özel konum seçimlerini, Git korumasını, no-copy davranışını, backup/restore'u, policy preservation'ı, farklı istemcileri ve temiz kurulum senaryolarını birlikte test et. Faz 8 baseline ve Türkçe kapanış kaydını yalnız bütün kapılar geçtikten sonra hazırla.

## Kabul ölçütleri

- İlk kullanımda varsayılan konum `<proje-kökü>/.krcn` olarak gösterilir.
- Kullanıcı varsayılan konumu kabul edebilir, başka bir konum seçebilir veya iptal edebilir.
- Açık yapılandırılmış mevcut kullanıcı evleri çalışmaya devam eder.
- Aynı proje sonraki çalıştırmalarda kayıtlı konumunu yeniden sormadan çözümler.
- `.krcn` izlenen Git içeriğine dönüşemez.
- Project discovery `.krcn` nedeniyle değişmez ve kendi ürettiği veriyi tekrar indekslemez.
- Proje kaynakları, dış veritabanları ve harici belgeler yerinde kalır.
- Git clone işlemi yerel veriyi varmış gibi göstermez; eksik çalışma alanını ve restore gereksinimini açıkça bildirir.
- Kullanıcı policy kayıtları byte ve anlam düzeyinde korunur.
- Eş zamanlı yazma sessiz veri kaybı üretemez.
- Faz 0-7 baseline testleri geçmeye devam eder.
- Her adım test, Türkçe commit ve push sonrasında tamamlanmış sayılır.
