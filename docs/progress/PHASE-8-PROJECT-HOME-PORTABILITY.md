# Faz 8 proje çalışma alanı taşınabilirliği

## Sonuç

Merkezi veya eski KRCN kullanıcı evini proje bazlı `.krcn` çalışma alanına veri kaybı olmadan taşıyan ve temiz proje klonunda geri yükleyen ortak akış tamamlandı.

## Migration sırası

1. Kaynak KRCN evi ve boş hedef salt okunur incelenir.
2. Proje konumu, Git izleme durumu ve yerel exclude etkisi exact plana alınır.
3. Kaynak kayıtlar secret ve makine yolu taramasından geçirilir.
4. Harici source binding konumları `unbound` bağımlılığa dönüştürülür; proje içeriği pakete alınmaz.
5. Proje evi manifesti taşınabilir pakete eklenir.
6. Açık onaydan sonra önce backup arşivi yazılır ve doğrulanır.
7. Git koruması uygulanır ve paket boş hedefe staging dizini üzerinden atomik olarak geri yüklenir.
8. Proje evi manifesti ve restore digest değeri doğrulanır.
9. Eski kaynak ev silinmez, taşınmaz veya değiştirilmez.

## Temiz makine kurtarma

Git clone yalnız proje kaynaklarını getirir. Yerel `.krcn` verisi için kullanıcı doğrulanmış backup arşivini ayrıca sağlar. `restore-project-home` işlemi boş hedefi, arşiv manifestini ve Git korumasını aynı exact plan içinde doğrular. Harici projeler ve veritabanları pakete kopyalanmaz; fiziksel konum değişmişse explicit rebind gerekir.

## Policy ve secret koruması

- Kullanıcı policy dosyaları byte düzeyinde korunur.
- `delete` reddi ve `select` izni gibi veritabanı sınırları migration sırasında yorumlanmaz veya yeniden yazılmaz.
- Secret dizinleri ve secret benzeri değerler normal backup paketine alınmaz.
- Kaynak proje dosyaları, harici belgeler ve veritabanı içerikleri backup ya da `.krcn` içine kopyalanmaz.

## Rollback yaklaşımı

Migration kaynağı her zaman korunur. Backup restore öncesinde tamamlandığı için kullanıcı eski konumu yeniden seçebilir veya doğrulanmış arşivden tekrar kurtarma yapabilir. Sistem kaynak evi otomatik silmez ve başarısız hedefi kaynak yerine geçerli saymaz.

## Doğrulama

Sentetik merkezi ev, Git projesi ve temiz klon ile şu durumlar test edildi:

- policy byte değerinin korunması;
- kaynak evin tüm dosya digest değerlerinin değişmemesi;
- proje kaynağının yerinde ve değişmeden kalması;
- proje dosyasının `.krcn` veya backup paketine girmemesi;
- secret dosyasının backup dışında bırakılması;
- target `.krcn` manifesti ve yerel Git exclude doğrulaması;
- temiz klonda backup restore;
- dolu hedefin içeriği korunarak reddedilmesi;
- CLI, SDK, MCP, plugin, Codex ve Claude istemcilerinin aynı migration planını alması.

Gerçek kullanıcı verisi veya gerçek proje dizini testte kullanılmadı.
