# Faz 11 proje kapsülü ve yerleşim v2 tamamlandı

## Sonuç

KRCN kullanıcı evi, proje kayıtlarını `projects/<project-id>` altında birbirinden ayıran yerleşim v2 yapısına kavuştu. Proje, binding, entegrasyon, bilgi, kalıcı çalışma geçmişi ve yeniden üretilebilir indeksler aynı proje kapsülünde yönetilir. Global ve makineye özel alanlar proje verisinden ayrıdır.

## Taşıma ve geriye uyumluluk

- Yerleşim v1 okunmaya devam eder.
- Yerleşim v1 için önce doğrulanmış yedek üreten exact-plan migration hazırdır.
- Taşıma sırasındaki her kaynak ve hedef hash ile sabitlenir.
- Kısmi hata otomatik geri dönüşü tetikler ve yedek korunur.
- Yeni yerleşim işareti tüm dosyalar doğrulandıktan sonra en son yazılır.

## Proje kapsülü taşınabilirliği

- `thin` paket kalıcı proje bağlamını taşır, yeniden üretilebilir indeksleri taşımaz.
- `ready` paket bütünlüğü doğrulanmış proje indekslerini de taşıyabilir.
- Proje kaynak dosyaları, secret değerleri, aktif kilitler ve çalışan süreç sahiplikleri pakete girmez.
- Fiziksel kaynak yolu taşınabilir kimlik sayılmaz. İçe aktarılan proje doğrulanmış rebind yapılana kadar kaynağa bağlı kabul edilmez.
- İçe aktarma mevcut kayıtların üzerine yazmaz ve çakışmada kapalı biçimde durur.

## Gerçek veri doğrulaması

Mevcut `gpu-fusion` kullanıcı verisi onaylı exact planla yerleşim v2 yapısına taşındı:

- 13 mevcut kayıt ve indeks proje kapsülüne veya global alana taşındı.
- Yerleşim ve kapsül tanımlayıcıları oluşturuldu.
- Taşıma öncesi depo dışında doğrulanmış geri dönüş arşivi oluşturuldu.
- Global `krcn project resume` proje, binding, bilgi kayıtları ve entegrasyon durumunu buldu.
- 1.754 kaynak dosyası ve 3.020 kod parçası taşınmış indeksten bütünlük kontrolüyle okundu.
- Kaynak proje dosyaları kopyalanmadı veya değiştirilmedi.

## Korunan sınırlar

- Yerel kullanıcı verisi Git'e eklenmedi.
- Proje kaynakları KRCN home içine kopyalanmadı.
- Secret değerleri taşınabilir paketlere eklenmedi.
- Kullanıcı verisi dry-run, exact plan ve açık onay olmadan değiştirilmedi.
- Eski yerleşim desteği sessizce kaldırılmadı.
