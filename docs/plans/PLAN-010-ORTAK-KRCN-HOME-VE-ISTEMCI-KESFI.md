# Plan 010: Ortak KRCN Home ve İstemci Keşfi

## Amaç

Proje kayıtlarını tek bir kullanıcı veri kökünde güvenle birleştirmek ve Codex, Claude Code ile OpenCode'un herhangi bir proje dizininden KRCN Core'u kendiliğinden bulup kullanmasını sağlamak.

## Kabul edilmiş kararlar

1. Ortak kullanıcı veri kökü `<shared-krcn-home>` olacaktır. Gerçek konum yalnızca yerel uygulama planında tutulacaktır.
2. `gpu-fusion` kaynak kayıtları `<gpu-fusion-project-home>` konumundan okunacaktır. Gerçek konum Git'e yazılmayacaktır.
3. Kaynak proje dosyaları kopyalanmayacak ve değiştirilmeyecektir.
4. Kaynak `.krcn` silinmeyecek, doğrulanmış geri dönüş kaynağı olarak korunacaktır.
5. Hedefteki mevcut `staging` içeriği değişmeden korunacaktır.
6. Kalıcı yedekler `<persistent-backup-root>` altında tutulacaktır. Gerçek konum Git'e yazılmayacaktır.
7. Başarılı birleşme ve doğrulama sonrasında kullanıcı düzeyindeki `KRCN_HOME` ortak veri köküne ayarlanacaktır.
8. Proje klasörlerine istemciye özel bağlam dosyaları eklenmeyecektir.

## Adımlar

### 1. Güvenli birleşme operasyonu

- `portability.merge-project-home` ortak application service operasyonunu geliştir.
- Kaynak ve hedef için secret-safe, doğrulanmış yedek oluştur.
- Çakışan kayıt yolu için revision ve payload hash karşılaştırması yap.
- Yalnızca eksik user-data kayıtlarını ekle.
- Runtime, derived, local-data, secret ve project-home manifestini dışarıda bırak.
- Kaynak ve mevcut hedef içeriğinin değişmediğini test et.

### 2. Gerçek `gpu-fusion` birleşmesi

- Exact plan üret ve kullanıcı onayına bağla.
- İki yedeği doğrula, planı uygula ve hedef kayıtlarını denetle.
- `gpu-fusion` source state verisini hedefte yeniden üret.
- Proje kökü ve KRCN Core kökünden erişimi doğrula.
- Git tarafından hiçbir `.krcn` verisinin izlenmediğini doğrula.
- Kullanıcı düzeyindeki `KRCN_HOME` değerini ortak veri köküne ayarla.

### 3. Çalışma dizinine göre proje eşleştirme

- Bulunulan dizini kayıtlı salt okunur source binding değerleriyle karşılaştır.
- Tam kök ve alt dizin eşleşmelerini destekle.
- Tek eşleşmede projeyi otomatik seç.
- Birden fazla eşleşmede tahmin yürütme, açık seçim iste.
- KRCN Core kökünden proje adı veya kimliğiyle çözümlemeyi destekle.

### 4. Kaldığı yerden devam özeti

- Eşleşen projenin kayıt, kaynak durumu, bilgi tabanı ve aktif iş durumunu tek özette sun.
- `Nerede kaldık?` gibi isteklerin istemci bağımsız bir KRCN operasyonuna yönlenmesini sağla.
- Fiziksel source locator, secret değerleri ve ham çalışma çıktısını public özette gösterme.

### 5. Kullanıcı düzeyinde istemci başlangıcı

- Codex için kullanıcı düzeyindeki global `AGENTS.md` başlangıç kuralını yönet.
- Claude Code ve OpenCode için resmi kullanıcı düzeyi yönerge konumlarını kullan.
- Mevcut kullanıcı dosyalarını yedekle ve yalnızca işaretli KRCN bölümünü yönet.
- Her istemciye aynı kısa görevi ver: oturum başlangıcında veya proje durumu sorulduğunda global `krcn` komutuyla çalışma dizimini çözümle.
- Ürün kurallarını istemci dosyalarına kopyalama, KRCN Core'a yönlendir.

### 6. Uçtan uca doğrulama

- Codex, Claude Code ve OpenCode başlangıç dosyalarının mevcut kullanıcı içeriğini koruduğunu doğrula.
- `gpu-fusion` kökünden otomatik proje eşleşmesini test et.
- KRCN Core kökünden `gpu-fusion` adıyla eşleşmeyi test et.
- Eşleşmeyen dizinde güvenli ve açıklayıcı sonuç üretildiğini doğrula.
- Tüm yerel testleri, repository doğrulamasını, wheel testini ve uzak CI kontrollerini çalıştır.

## Tamamlanma ölçütü

Kullanıcı Codex, Claude Code veya OpenCode'u kayıtlı bir proje dizininde açıp yalnızca hedefini ya da `Nerede kaldık?` sorusunu yazdığında istemci KRCN Core'u bulur, ortak kullanıcı veri kökünden doğru projeyi eşler ve güvenli çalışma bağlamını getirir. Proje kaynakları yerinde kalır; mevcut kullanıcı kayıtları, politikalar, secret referansları ve hedef staging içeriği korunur.
