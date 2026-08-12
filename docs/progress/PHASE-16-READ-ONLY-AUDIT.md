# Faz 16 salt okunur denetim ve kaynak güvenliği

## Sonuç

Altı hedef kaynak proje ve eski görev merkezi hiçbir dosya değiştirilmeden incelendi. Kaynaklar KRCN'e kopyalanmadı ve hiçbir kullanıcı verisi planı uygulanmadı.

## Proje denetimi

- `plsql-test-sync`, `schema-compare-platform`, `schema-transform-platform`, `utplsql`, `sky-microservis` ve `sky-ui` kaynakları mevcut.
- Projelerdeki modified, deleted, staged ve untracked kullanıcı değişiklikleri korunuyor. Clean, reset veya otomatik dosya düzenleme yapılmadı.
- `sky-ui` dizini kendi metadata bilgisinden `call-center-ui` proje kimliğini üretiyor. Bu ilişki alias olarak korunacak ve sessizce yeniden adlandırılmayacak.
- Generated frontend çıktıları, DDL çıktıları, eski AI yedekleri, binary araç paketleri ve arşiv dosyaları kaynak indeksine alınmamalı.
- Bazı uygulama configleri, bağlantı metadata belgeleri ve operasyonel proje belgeleri secret, credential veya makineye özel locator sınıfı taşıyor. Eşleşen dosya içeriği değer açığa çıkarılmadan indeks dışında bırakılmalı.

## Görev mirası denetimi

- `schema-compare-platform` için iki aktif ve on bir tamamlanmış kayıt yüksek güvenle sınıflandırıldı.
- `schema-transform-platform` için üç tamamlanmış kayıt ve ayrıntısı eksik yedi tarihsel aday bulundu.
- Bir görev kimliğinin iki projede kullanıldığı görüldü. Work Graph kimliği proje kapsamıyla birlikte ele alınmalı.
- Diğer dört proje için eski merkezde doğrulanmış görev kaydı bulunmadı. Proje belgesi, deploy logu veya README otomatik görev sayılmayacak.
- Yalnız görev kimliğini açıkça taşıyan commit ilişkileri kesin evidence kabul edilecek. Zamansal veya tematik benzerlik otomatik bağ oluşturmayacak.

## Eklenen koruma

- Ortak import policy generated, vendor, binary, archive, dump, log ve eski AI yedeklerini kaynak keşfinden dışlar.
- Kaynak kod indeksi secret assignment, credential URI, özel anahtar, token, kişisel locator ve IP detector sonuçlarını içerik değerini saklamadan atlar.
- Detector policy digest içine alınır. Policy değiştiğinde mevcut kaynak kod indeksi stale olur ve güvenli yeniden entegrasyon gerekir.
