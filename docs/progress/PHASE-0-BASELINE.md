# Faz 0 baseline inceleme raporu

## Amaç

Mevcut canlı sistem ile baseline adayını veri kaybı, bilgi sızıntısı ve davranış bozulması riski oluşturmadan incelemek. Bu rapor bir aktarım kararı değildir. Kaynak kod veya yerel veri repository'ye alınmamıştır.

## İnceleme yöntemi

- Kaynaklar salt okunur olarak tarandı.
- Dosyalar göreli yol ve SHA-256 ile karşılaştırıldı.
- Core adayı, runtime, user-data, derived, secrets ve geliştirme artifaktları ayrı değerlendirildi.
- Secret ve taşınabilirlik taramasında değerler raporlanmadı. Yalnızca risk kategorileri kullanıldı.
- Testler geçici bir kopyada ve ağ erişimi teknik olarak engellenmiş durumda çalıştırıldı.
- Yerel kaynak konumları ve özel proje kimlikleri repository belgelerine yazılmadı.

## Envanter özeti

| Kaynak sınıfı | Dosya sayısı | Yaklaşık boyut | Yorum |
|---|---:|---:|---|
| Canlı referans | 507 | 698 MB | İşler, proje verisi, indeksler ve runtime durumu içeriyor |
| Mimari ve baseline çalışma alanı | 119 | 1,77 MB | Tasarım belgeleri ve baseline adayı içeriyor |
| Baseline adayı | 86 | 665 KB | Core, test, örnek proje ve runtime kalıntıları birlikte bulunuyor |

Canlı referans ile baseline adayı arasındaki ham karşılaştırma:

| Durum | Dosya sayısı | Yorum |
|---|---:|---|
| Aynı | 62 | Ortak core, şema, agent, skill ve test dosyaları ağırlıkta |
| Farklı | 7 | Olay günlüğü, README, proje konumu ve cache farkları |
| Yalnızca baseline adayında | 17 | Test fixture ve cache/runtime kalıntıları |
| Yalnızca canlı referansta | 438 | Büyük oranda iş, proje, runtime ve derived veri |

Core odaklı filtrede cache dosyaları dışarıda bırakıldığında 29 dosya canlı sistem ile birebir aynıdır. Baseline adayına özel sekiz dosya test fixture kapsamındadır.

## Mevcut çalışan yüzey

Baseline sürümü `0.1.0-taslak` olarak kayıtlıdır. CLI şu ana grupları içerir:

- workspace root ve validate;
- project onboard, list ve rescan;
- task list, checkpoint ve kaldığı yer;
- source index build, status ve query;
- memory index ve semantic query;
- database connection metadata ve database index;
- birleşik arama;
- lock yönetimi;
- handoff;
- skill list ve show.

CLI tek bir Python dosyasında 3.669 satır ve 163.852 byte boyutundadır. Komut ayrıştırma elle yapılmaktadır ve standart bir `--help` yüzeyi yoktur.

## Test sonucu

Testler geçici kopyada çalıştırıldı. Ağ çağrıları engellendi.

- Skill yükleme testi: 23 kontrol geçti.
- Regresyon testi: 38 kontrol geçti, 1 kontrol kaldı, 8 opsiyonel kontrol uyarılı olarak atlandı.
- Kalan kontrol, gerçek bir davranış hatasından çok testin ortam bağımlılığını gösteriyor. Test eksik secret environment değişkenini beklerken CLI önce opsiyonel database driver eksikliğini bildiriyor.

Regresyon testi hermetic değildir. İş istasyonuna özel yollar ve belirli kurulum adları kod içinde sabitlenmiştir. Bu test doğrudan aktarılamaz.

## Kritik bulgular

### 1. Yerel veri ile core aynı ağaçta

Core dosyaları, runtime durumu, olay günlüğü, kullanıcı tercihleri, proje belleği, görevler, indeksler ve bağlantı metadata dosyaları aynı kök altında tutuluyor. Bu durum güvenli update ve release işlemini zorlaştırıyor.

### 2. Baseline adayı taşınabilir değil

Agent talimatları, testler, proje metadata dosyaları ve bazı belgeler iş istasyonuna özel mutlak yollar içeriyor. Testlerde belirli proje ve bağlantı örnekleri bulunuyor. Bunlar sanitize edilmeden repository'ye alınamaz.

### 3. Varsayılan embedding davranışı yerel veri politikasıyla uyuşmuyor

CLI, host makinedeki başka bir araç ayarını otomatik okuyup erişilebilir bir embedding gateway bulursa metin parçalarını uzak servise gönderebiliyor. KRCN Core'da uzak embedding açık ve bilgilendirilmiş bir opt-in olmadan çalışmamalı. Varsayılan davranış offline olmalıdır.

### 4. Workspace referansları kırık

Workspace ayarı iki policy dosyasına referans veriyor ancak bu dosyalar baseline adayında yok. Benzer isimli engine dosyaları mevcut. `validate` yalnızca dosya varlığı seviyesinde kaldığı için bu referans sorununu tam olarak yakalamıyor.

### 5. Testler ortam ve veri bağımlı

Testler makineye özel dizinleri, kayıtlı projeleri ve opsiyonel Python paketlerini varsayıyor. Core testleri hermetic fixture ile, entegrasyon testleri ise açık capability koşullarıyla ayrılmalı.

### 6. Secret değeri bulunmadı ancak hassas metadata var

Taramada private key veya GitHub PAT bulunmadı. Database bağlantı kayıtları parolayı literal olarak tutmuyor ve secret reference kullanıyor. Buna rağmen host, kullanıcı, servis, şema, IP, e-posta ve connection metadata hassas kabul edilmeli ve core repository dışında kalmalı.

## Aktarım sınıfları

### A. Doğrudan aday, yine de inceleme gerekli

- generic schema tanımları;
- engine ve policy varsayımları;
- generic agent registry tanımları;
- platformdan bağımsız launcher dosyaları;
- generic skill sözleşmeleri.

### B. Dönüştürülerek alınabilir

- monolitik CLI;
- workspace ayarları;
- README ve agent talimatları;
- test runner ve fixture dosyaları;
- model registry örnekleri;
- generic memory şablonları.

Bu grupta mutlak yollar, yerel kimlikler, otomatik ağ davranışı ve canlı veri varsayımları kaldırılmalıdır.

### C. Yalnızca bilgi kaynağı

- mimari araştırma belgeleri;
- canlı sistemden öğrenilen davranışlar;
- kullanıcıya veya projeye özel skill örnekleri;
- geçmiş karar ve iş kayıtları.

Bu bilgiler olduğu gibi kopyalanmaz. Genelleştirilmiş gereksinim veya test senaryosuna dönüştürülür.

### D. Repository'ye alınmayacak

- iş ve talep dosyaları;
- proje belleği ve proje metadata kayıtları;
- olay günlükleri ve checkpoint durumu;
- database bağlantı metadata dosyaları;
- SQLite ve vector index dosyaları;
- cache, bytecode ve IDE dosyaları;
- backup ve üretilmiş raporlar;
- e-posta, IP, mutlak yol veya kurum bilgisi içeren yerel belgeler;
- secret ve yerel araç ayarları.

## Sonuç

Mevcut baseline tamamen reddedilmeyecek. Çalışan core davranışı korunacak ancak kaynak ağaç olduğu gibi kopyalanmayacak. İlk uygulama adımı ownership manifestini ve offline-first provider politikasını oluşturmak, ardından yalnızca onaylanan core dosyalarını sanitize edilmiş bir staging alanına almaktır.

## Sonraki onay noktası

Kullanıcı onayından sonra Faz 1 şu sırayla başlayabilir:

1. Ownership manifest şeması tanımlanır.
2. Repository dizin yapısı oluşturulur.
3. Offline-first provider politikası yazılır.
4. Sanitize ve import kontrol listesi makinece doğrulanabilir hale getirilir.
5. Onaylanan core adayları staging alanına alınır.
6. Hermetic baseline testleri yeniden yazılır.
