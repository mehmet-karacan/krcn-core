# PLAN-003 - Yerel çalışma alanı ve entegrasyon modeli

## Durum

Tamamlandı. Faz 2 baseline'ı `.ai/phase-2-baseline.json`, kapanış kanıtı `docs/progress/PHASE-2-COMPLETION.md` içinde tutulur.

## Amaç

Projeleri, belgeleri ve entegrasyonları içeriklerini KRCN Core repository'sine kopyalamadan mantıksal kimliklerle kaydetmek; fiziksel konumları yerel source binding kayıtlarında tutmak ve tüm erişimleri capability, policy ve sahiplik kapılarından geçirmek.

## Değişmez sınırlar

- Canlı ve şablon referans kaynakları varsayılan olarak salt okunurdur.
- Yerel proje içeriği Git'e veya uzak provider'a kendiliğinden gönderilmez.
- Onboarding kaynak dizinine dosya yazmaz.
- Fiziksel yollar core kayıtlarına, loglara veya genel context çıktısına girmez.
- User-data kayıtları yalnızca dry-run ve gerekli kullanıcı onayıyla değiştirilir.
- Secret değerleri integration metadata içine yazılmaz; yalnızca secret reference tutulur.
- Bir adapter yalnızca açıkça ilan ettiği capability'leri kullanabilir.
- Sembolik bağlantılar ve kaynak kökü dışına çıkan yollar varsayılan olarak takip edilmez.

## Uygulama adımları

### Adım 1 - Faz 2 bağlamı

- Aktif çalışma kaydını Faz 2'ye geçir.
- Uygulama sırasını ve kabul ölçütlerini kaydet.
- Faz 1 baseline'ını değişmez başlangıç noktası olarak bağla.

### Adım 2 - Yerel kayıt deposu

- Workspace, project ve source binding kayıtlarını yerel user-data altında ayır.
- Atomic write, revision kontrolü ve duplicate kimlik denetimi ekle.
- Public özetlerde fiziksel locator değerlerini maskele.

### Adım 3 - Salt okunur onboarding

- Sentetik bir proje dizinini source binding üzerinden tanıt.
- Onboarding öncesi plan ve dry-run üret.
- Kaynak dizine yazmadan workspace ve project kayıtlarını oluştur.

### Adım 4 - Keşif adapter'ı

- Proje dosya ve teknoloji işaretlerini salt okunur tara.
- Engellenmiş yolları, boyut sınırını ve sembolik bağlantıları uygula.
- Sonuçları kaynak kanıtı ve revision bilgisiyle döndür.

### Adım 5 - Capability ve policy zinciri

- Adapter capability sözleşmesini source binding ile birleştir.
- Her dış veya yerel işlemden önce etkili kullanıcı policy sonucunu değerlendir.
- Bildirilmeyen capability kullanımını engelle.

### Adım 6 - Entegrasyon ve secret reference

- Entegrasyon metadata şemasını oluştur.
- Secret literal değerlerini reddet.
- Secret provider'a taşınabilir reference dışında erişim verme.

### Adım 7 - Rescan ve değişiklik tespiti

- Kaynak revision ve içerik parmak izlerini karşılaştır.
- Yalnızca değişen metadata için plan üret.
- User-data güncellemesini mutasyon kapısına bağla.

### Adım 8 - CLI ve istemci adaptörleri

- Güvenli onboarding, list, inspect ve rescan servislerini CLI'a bağla.
- MCP, SDK ve plugin'lerin aynı servis sözleşmesini kullanabileceği girişleri tanımla.
- İstemciye göre farklı güvenlik davranışı oluşmasını engelle.

### Adım 9 - Entegrasyon testleri

- Sentetik fixture ile temiz workspace oluştur.
- Kaynak dizine yazılmadığını ve fiziksel yolların çıktıya sızmadığını doğrula.
- Policy, capability, secret ve ağ sınırlarını hermetik test et.

### Adım 10 - Faz 2 kapanışı

- Faz 2 baseline manifestini ve ilerleme raporunu oluştur.
- Temiz kurulum ve mevcut workspace uyumluluğunu doğrula.
- Faz 3 `merge into` motoruna geçiş sınırını kaydet.

## Kabul ölçütleri

- Bir proje içeriği kopyalanmadan mantıksal kimlikle kaydedilebilmeli.
- Source binding fiziksel konumu yalnızca yerel user-data içinde tutmalı.
- Kaynaklar varsayılan olarak salt okunur olmalı.
- Onboarding ve rescan kaynak dizine yazmamalı.
- User-data mutasyonları dry-run ve onay kapısından geçmeli.
- Uzak provider varsayılan olarak kapalı kalmalı.
- Secret literal değeri hiçbir metadata veya log çıktısına girmemeli.
- Tüm testler ağ kapalıyken geçmeli.

## Onay kapıları

Sentetik fixture ve yeni core kodu doğrudan geliştirilebilir. Canlı kullanıcı verisinin kaydedilmesi, mevcut user-data migration'ı, gerçek entegrasyon bağlantısı veya uzak provider kullanımı ayrı dry-run ve açık kullanıcı onayı gerektirir.
