# ADR 014: V1 ajan kuyruğu SQLite ile devam eder

## Durum

Kabul edildi.

## Karar

KRCN Core V1, proje kapsüllerindeki mevcut SQLite ajan kuyruğunu kullanmaya
devam eder. Redis Streams, NATS JetStream ve PostgreSQL queue bu fazda ürün
bağımlılığı veya çalışma zamanı adapterı olarak eklenmez.

## Ölçüm

Gerçek `AgentRuntimeQueue` kodu geçici ve sentetik yükle ayrı süreçlerde
ölçüldü:

- Küçük profil: 1 proje, 1 işçi, 100 iş. Claim p95 46.174 ms ve throughput
  12.392 iş/saniye.
- Orta profil: 8 proje, 4 işçi, toplam 400 iş. Claim p95 60.361 ms ve throughput
  46.260 iş/saniye.
- Lease recovery, eski fencing reddi, SQLite integrity ve dosya tabanlı yedek
  geri yükleme doğrulandı.

Her iki kabul profili de sürümlü eşikleri geçti. Ölçüm, proje başına ayrı
kuyruk sınırının korunmasına bağlıdır. Tek proje kuyruğunda çok yüksek backlog
ve eşzamanlı yazar yoğunluğu ayrı bir stres durumu olarak izlenir.

## Gerekçe

Mevcut sistem local-first, çevrimdışı, sıfır servis kurulumu ve proje kapsülü
ile birlikte yedeklenebilir çalışma sağlıyor. Harici kuyruk erken eklenirse
secret, TLS, servis yaşam döngüsü, yedek, ağ ve operasyon maliyeti oluşacak.
Güncel ölçüm bu maliyeti haklı çıkaran bir zorunluluk göstermiyor.

## Geçiş tetikleyicileri

Aşağıdaki durumlardan biri ölçümle doğrulanırsa adaylar ayrı bir ADR ve exact
adoption planıyla yeniden değerlendirilir:

- Claim p95 eşiğinin tekrarlanan referans ölçümlerde aşılması.
- Aynı runtime durumuna birden fazla makinenin yazması gerekmesi.
- Yedek ve geri yükleme hizmet seviyesinin karşılanmaması.
- Runtime depolama büyümesinin kabul edilemez hale gelmesi.
- Merkezi ekip erişiminin gerçek ürün gereksinimine dönüşmesi.

## Sonuçlar

- Yeni servis, lisans, sağlayıcı veya API maliyeti yoktur.
- Mevcut lease, heartbeat, fencing ve recovery sözleşmeleri değişmez.
- Dış adayların performansı ölçülmüş gibi gösterilmez.
- Benchmark kodu üretim queue adapterı sayılmaz.
- Geçiş kararı yetki vermez ve kullanıcı verisini kendiliğinden taşımaz.
