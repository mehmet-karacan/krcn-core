# Faz 8 proje çalışma alanı initialization

## Sonuç

Proje bazlı `.krcn` çalışma alanını kullanıcı kararı, exact plan ve açık onay olmadan oluşturmayan initialization katmanı tamamlandı.

## Uygulanan davranış

1. Varsayılan konum kabul edilmeden initialization planı üretilemiyor.
2. Hedef yoksa yalnız mevcut ve güvenli bir ana dizin altında oluşturulabiliyor.
3. Hedef dolu fakat geçerli KRCN manifesti taşımıyorsa sahipliği tahmin edilmiyor ve işlem duruyor.
4. Layout version 2 proje evi `project-home.json` manifestiyle açıkça tanımlanıyor.
5. Manifest fiziksel proje yolunu, source içeriğini veya secret değerini taşımıyor.
6. Git worktree içindeki çalışma alanı için tracked ve ignore durumu salt okunur inceleniyor.
7. `.krcn` içeriği Git tarafından zaten izleniyorsa hiçbir veri silinmeden veya untrack edilmeden işlem duruyor.
8. Ignore kuralı eksikse takip edilen `.gitignore` yerine yerel `.git/info/exclude` değişikliği ayrı mutation etkisi olarak plana ekleniyor.
9. Git exclude ve manifest yazımı aynı donmuş plan üzerinden uygulanıyor; ikinci etki başarısız olursa ilk etki eski byte değerine geri alınıyor.
10. Aynı çalışma alanı yeniden incelendiğinde yeni mutation üretmeden geçerli manifest tanınıyor.

## Sahiplik ve discovery

- `.krcn/project-home.json` ve `.krcn/local-data/**` user-data olarak sınıflandırıldı.
- `**/.krcn/**` discovery ve import taramasının kaynak kapsamından çıkarıldı.
- KRCN proje kaynaklarını `.krcn` içine kopyalamıyor.
- Harici veritabanları taşınmıyor; yalnız ileride policy ve secret reference kullanan entegrasyon kayıtlarıyla bağlanacak.

## Doğrulama

Sentetik Git ve Git olmayan proje dizinlerinde şu durumlar test edildi:

- onaysız initialization reddi;
- varsayılan konumun oluşturulması;
- yerel Git exclude planı;
- mevcut repository ignore davranışı;
- proje dışındaki özel konum;
- belirsiz dolu hedefin korunması;
- tracked `.krcn` verisinin korunarak reddedilmesi;
- idempotent yeniden inceleme;
- plan sonrasında değişen Git exclude içeriğinin stale plan üretmesi.

Gerçek kullanıcı projesi veya kullanıcı verisi bu testlere alınmadı.
