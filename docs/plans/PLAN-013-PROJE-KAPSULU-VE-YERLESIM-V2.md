# Plan 013 - Proje kapsülü ve yerleşim v2

## Durum

Tamamlandı.

## Amaç

Dağınık KRCN kullanıcı verisini proje kimliği altında toplamak, projeler büyüdüğünde talep, defect, görev, bilgi ve derived kayıtlarının birbirine karışmasını önlemek ve tek proje bağlamını güvenli biçimde taşınabilir hale getirmek.

## Hedef yerleşim

Her proje için `projects/<project-id>` altında bağımsız bir kapsül bulunur. Kapsül; proje kaydı, mantıksal binding, entegrasyon, bilgi, çalışma kaydı, kalıcı runtime geçmişi ve yeniden üretilebilir derived veriyi proje kapsamına göre ayırır.

Makineye özel mutlak yollar, secret değerleri, aktif kilitler ve çalışan süreç sahiplikleri kapsülün taşınabilir bölümüne girmez. Dış proje kaynakları yerinde okunur ve KRCN alanına kopyalanmaz.

## İş paketleri

1. Yerleşim v2 ve proje kapsülü şemalarını tanımla.
2. Yerel store için v1 okuma uyumluluğu ve v2 proje bazlı yazma desteği ekle.
3. Kaynak kod ve hibrit indeks yollarını v2 yerleşimine bağla.
4. V1 kullanıcı home için yedekli, exact-plan kontrollü ve geri alınabilir migration oluştur.
5. `thin` ve `ready` proje kapsülü dışa aktarma sözleşmesini oluştur.
6. Mevcut bir KRCN home içine çakışmasız kapsül içe aktarma ve kaynak rebind akışını oluştur.
7. Doctor, sahiplik ve portable backup kurallarını yeni yerleşimle uyumlu hale getir.
8. Windows, macOS ve Linux yol davranışını test et.
9. Faz kabul testlerini ve ilerleme kaydını tamamla.

## Kabul ölçütleri

- Yeni yerleşimde bir projenin kullanıcı verisi `projects/<project-id>` altında bulunur.
- Global, makineye özel, runtime, derived ve secret sınırları birbiriyle çakışmaz.
- V1 veri plan hazırlama sırasında değişmez.
- Migration uygulanmadan önce doğrulanmış yedek üretilir.
- Başarısız migration mevcut veriyi kaybettirmez.
- Kapsül dışa aktarma proje kaynak dosyalarını, secret değerlerini ve aktif kilitleri içermez.
- `ready` paket doğrulanmış derived indeksleri taşıyabilir; `thin` paket bunları dışarıda bırakır.
- İçe aktarılan fiziksel kaynak yolu güvenilir kabul edilmez ve doğrulanmış rebind gerekir.
- Eski v1 home okumaları geriye uyumlu çalışır.
- Tüm repository testleri ve doctor kontrolleri geçer.

## Tamamlanma kuralı

Plan yalnızca kod, şema, migration, kapsül aktarımı, belgeler ve platformlar arası testler tamamlandıktan sonra `Tamamlandı` olarak işaretlenir.
