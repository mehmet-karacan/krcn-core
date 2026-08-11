# PLAN-007 - Release, kalite ve taşınabilirlik

## Durum

Aktif. Mehmet KARACAN'ın açık onayıyla Faz 6 başlatıldı.

## Amaç

KRCN Core'u temiz kurulum, mevcut kurulum güncellemesi ve bilgisayar değişimi senaryolarında güvenilir biçimde çalıştırmak. Kullanıcıya ait KRCN kayıtları tek bir taşınabilir kullanıcı evinde korunacak. Dış proje dosyaları hiçbir zaman bu alana kopyalanmayacak; sistem projeyi kayıtlı dizininden salt okunur tanıyacak ve yol değiştiğinde doğrulanmış yeniden bağlama isteyecek.

## Değişmez sınırlar

- Core Git repository ile KRCN kullanıcı evi ayrı tutulur.
- Proje kaynakları backup, restore, migration veya rebind sırasında kopyalanmaz, taşınmaz, değiştirilmez ve Git'e eklenmez.
- Tek kullanıcı evi KRCN bağlamını, kullanıcı policy'lerini, knowledge, memory, iş kayıtlarını ve çalışma durumunu taşır.
- Dış proje dizini yeni makinede ayrıca bulunmalıdır. Yol değişirse exact plan ile yeniden bağlanır.
- Secret değerleri taşınabilir pakete alınmaz; yalnız güvenli referanslar ve eksik bağımlılık raporu taşınabilir.
- Kullanıcının `SELECT` dışında database işlemi istememesi veya `DELETE` işlemini yasaklaması gibi policy'ler migration ve restore sırasında aynen korunur.
- Repo içindeki mevcut `.krcn` verisi otomatik taşınmaz. Ayrı, yedekli ve geri alınabilir migration gerekir.
- Büyük veya uyumsuz bir dönüşüm sessiz uygulanmaz; ayrı migration çıktısı ve açık kullanıcı onayı ister.
- Testler yalnız sentetik geçici dizinlerle çalışır.
- Uzun tire karakterleri kullanılmaz.

## Uygulama adımları

### Adım 1 - Faz sınırı ve kabul ölçütleri

Taşınabilir kullanıcı evi, dış kaynak, secret, recovery ve migration sınırlarını belgele. Mevcut Faz 5 baseline'ını değişmez giriş olarak kaydet.

### Adım 2 - Taşınabilir kullanıcı evi

CLI ve ortak servislerin aynı kullanıcı evini çözmesini sağla. Açık `--data-root` seçimini koru; ortam ve platform varsayılanlarını makine yolu repository içine yazmadan uygula.

### Adım 3 - Dış proje kimliği ve kopyalamama garantisi

Source binding kayıtlarına yeniden bağlamada kullanılabilecek içerik kimliği ekle. Kimlik üretimi yalnız salt okunur metadata ve içerik özeti kullansın; kaynak dosyalara yazmasın.

### Adım 4 - Yeniden bağlama

Eksik veya taşınmış proje dizini için inspect, plan, exact-plan approval, apply ve verify akışı oluştur. Uyuşmayan proje kimliğinde işlemi durdur.

### Adım 5 - Taşınabilir backup

Yalnız kullanıcı evini kapsayan, dış kaynakları ve secret değerlerini dışlayan doğrulanabilir backup manifesti ve arşivi üret.

### Adım 6 - Restore

Yeni bir kullanıcı evine dry-run, exact plan, apply ve verify aşamalarıyla restore uygula. Mevcut hedefi ezme ve eksik dış kaynakları açıkça raporla.

### Adım 7 - Eski `.krcn` migration

Repo içindeki eski veri kökü için ayrı inspect, plan, backup, apply, verify ve rollback akışı oluştur. Gerçek kullanıcı verisi üzerinde otomatik işlem yapma.

### Adım 8 - Platform ve istemci eşitliği

Windows ve macOS yol çözümünü hermetik test et. CLI, SDK, MCP, plugin ve AI istemcilerinin aynı kullanıcı evi ve güvenlik kararlarını kullanmasını doğrula.

### Adım 9 - Release ve kalite kapıları

CI, paketleme, doctor, release manifesti, offline kurulum ve rollback kontrollerini Faz 6 sözleşmeleriyle tamamla.

### Adım 10 - Bütünleşik kapanış

`clone -> install -> restore/init -> doctor -> run` ile `pull -> merge into -> verify` senaryolarını otomatik test et. Faz 6 baseline ve Türkçe kapanış raporunu oluştur.

## Kabul ölçütleri

- KRCN kullanıcı evi tek başına yedeklenebilir ve uyumlu bir core kurulumu altında geri yüklenebilir.
- Backup içinde dış proje dosyası, mutlak proje yolu veya secret değeri bulunmaz.
- Dış proje kaynakları onboarding, discovery, backup, restore ve rebind boyunca değişmeden kalır.
- Taşınmış bir proje yalnız doğrulanmış kimlik ve açık kullanıcı onayıyla yeniden bağlanır.
- Restore, kullanıcı policy'lerini zayıflatmaz ve mevcut hedef verisini sessizce ezmez.
- Repo-local veri migration'ı ayrı plan, backup ve rollback kanıtı olmadan uygulanmaz.
- Windows ve macOS aynı mantıksal veri düzenini ve manifestleri kullanır.
- Temiz kurulum ve güncelleme akışları test, doctor ve baseline kanıtlarıyla kapanır.

