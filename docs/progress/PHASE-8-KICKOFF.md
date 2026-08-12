# Faz 8 başlangıcı

## Sonuç

Faz 8, Mehmet KARACAN'ın açık isteğiyle başlatıldı. İlk mimari karar olarak proje kapsamındaki varsayılan KRCN kullanıcı evinin `<proje-kökü>/.krcn` olması kabul edildi.

## Başlangıç noktası

Faz 0-7 baseline tamamlanmış ve `2ab1cb1` commitinde repository testleri, doğrulama araçları ve doctor kontrolleri temiz durumdadır. Faz 8 bu baseline üzerinde küçük ve doğrulanabilir değişikliklerle ilerleyecek.

Mevcut Faz 6 davranışı kullanıcı evini proje dizininden ayrı çözümlemektedir. Yeni proje bazlı varsayılan bu davranışı sessizce değiştirmeyecek. Önce resolution planı üretilecek, kullanıcıya fiziksel konum ve taşıma sınırı gösterilecek, ardından exact-plan onayıyla initialization uygulanacaktır.

## Kullanıcı deneyimi kararı

İlk kullanımda sistem:

1. Proje kökünü bulacak.
2. `<proje-kökü>/.krcn` konumunu önerecek.
3. Dizin içeriğinin Git'e veya uzak servislere otomatik gönderilmeyeceğini açıklayacak.
4. Git clone işleminin bu yerel veriyi geri getirmeyeceğini bildirecek.
5. Varsayılan konumu kullanma, farklı bir konum seçme veya iptal seçeneklerini sunacak.
6. Kullanıcı kararı olmadan dizin oluşturmayacak.

## Korunan alanlar

- Bu başlangıç adımında gerçek proje veya kullanıcı verisi oluşturulmadı, taşınmadı ya da değiştirilmedi.
- Harici proje içerikleri repository'ye alınmadı.
- Kullanıcı policy'leri ve secret değerleri okunmadı.
- Faz 7 baseline değiştirilmedi.
- Uzak provider veya ağ işlemi kullanılmadı.
