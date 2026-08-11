# PLAN-008 - Doğal dille proje öğrenme

## Durum

Aktif. Mehmet KARACAN'ın açık isteğiyle başlatıldı.

## Amaç

Kullanıcının yalnız proje dizinini vermesi veya "projeyi öğren", "tanı", "tanıt" ya da "entegre et" demesi yeterli olacak. Sistem proje adını ve taşınabilir kimlikleri güvenli biçimde türetecek, dizini salt okunur inceleyecek, exact planı gösterecek ve tek kullanıcı onayından sonra onboarding ile ilk discovery kayıtlarını tamamlayacak.

## Değişmez sınırlar

- Proje dosyaları KRCN kullanıcı evine veya core repository'ye kopyalanmaz.
- Proje dizinine dosya yazılmaz ve identity marker eklenmez.
- Doğal dil tek başına mutation onayı değildir.
- Exact plan gösterilmeden user-data kaydı oluşturulmaz.
- Varsayılan source binding salt okunurdur.
- Policy, secret, uzak provider ve write capability değeri tahmin edilmez.
- Kullanıcının mevcut policy kayıtları değiştirilmez veya zayıflatılmaz.
- Bütün istemciler aynı `project.learn` service operation değerini kullanır.

## Uygulama adımları

### Adım 1 - Kapsam ve güvenlik sınırı

Doğal dil, dizin, güvenli inference, no-copy, exact plan ve istemci eşitliği kurallarını kaydet.

### Adım 2 - Intent ve dizin çözümleme

Türkçe ve İngilizce öğrenme, tanıma, tanıtma, onboarding ve entegrasyon ifadelerini deterministic olarak tanı. Yalnız mevcut mutlak dizin verildiğinde öğrenme niyetini güvenli varsayım olarak kabul et.

### Adım 3 - Metadata inference

Project marker veya dizin adından görünen ad ile taşınabilir kimlikler üret. Yerel çakışmalarda deterministic numeric suffix kullan.

### Adım 4 - Birleşik öğrenme planı

Read-only onboarding ve ilk discovery sonucunu workspace, project, source binding ve source state kayıtları için tek exact planda birleştir.

### Adım 5 - Ortak servis ve CLI

`project.learn`, `krcn project learn <dizin>` ve `krcn ask <istek>` girişlerini aynı application service davranışına bağla.

### Adım 6 - İstemci yönlendirme

Codex, Claude, MCP, plugin ve diğer AI istemcilerinin proje öğrenme ifadelerini ortak service operation değerine yönlendirmesi için canonical sözleşmeyi ekle.

### Adım 7 - Bütünleşik kapanış

Dizin-only, Türkçe ve İngilizce prompt, path boşluğu, collision, no-copy, stale plan, policy preservation ve istemci eşitliği senaryolarını test et. Baseline ve Türkçe kapanış raporunu oluştur.

## Kabul ölçütleri

- Kullanıcıdan workspace, project veya binding kimliği istenmez.
- Var olan mutlak proje dizini tek başına yeterlidir.
- Desteklenen doğal dil ifadeleri aynı proje öğrenme planını üretir.
- Plan bütün inferred alanları ve etkileri kullanıcıya gösterir.
- Tek exact-plan onayı onboarding ve ilk discovery kayıtlarını tamamlar.
- Kaynak proje byte ve zaman bilgileri değişmez.
- Proje kullanıcı evinin içine kopyalanmaz.
- Aynı directory yeniden öğrenilmek istendiğinde duplicate kayıt oluşturulmaz.
- Bütün istemciler aynı plan ve güvenlik kararını alır.

