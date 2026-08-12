# Kullanıcı Düzeyi İstemci Başlangıcı

## Durum

Codex, Claude Code ve OpenCode için ortak `client.bootstrap` operasyonu geliştirildi.

## Mimari sonuç

İstemciler KRCN'i proje dizinindeki ek bir dosyadan değil, kendi kullanıcı düzeyindeki global yönerge dosyasından tanır. Global bölüm yalnızca ortak `krcn` komutuna yönlendirir. Proje eşleştirme, kaldığı yer özeti, policy, ownership ve exact-plan kuralları KRCN Core içinde kalır.

## Güvenlik ve koruma

- Üç istemci aynı application service operasyonunu kullanır.
- Public plan hiçbir kullanıcı profili veya fiziksel dosya yolu açıklamaz.
- Mevcut dosyanın ve üretilecek dosyanın hash değerleri exact plana bağlanır.
- Mevcut istemci içeriği secret-like taramadan geçmeden yedeklenmez.
- Mevcut dosyalar değiştirilmeden önce aktif KRCN home içindeki local-data alanına yedeklenir.
- Yalnızca işaretli KRCN bölümü yönetilir; önceki ve sonraki kullanıcı içeriği korunur.
- Stale plan ve bozuk marker yapısı yazma öncesinde reddedilir.
- Kesinti halinde daha önce değiştirilen istemci dosyaları otomatik geri alınır.
- Aynı içerik tekrar kurulduğunda işlem no-op olur.

## Yerel mevcut durum

- Codex kullanıcı yönerge dosyası mevcut ve boştur.
- Codex global override dosyası bulunmamaktadır.
- Claude Code kullanıcı yönerge dosyası henüz bulunmamaktadır.
- İlk incelemede OpenCode kullanıcı yönerge dosyası mevcuttu ve korunması gereken kullanıcı içeriği taşıyordu.

Bu durumlar yalnızca yerel dry-run planında kullanılacak, Git'e kullanıcı dosyası veya fiziksel yol yazılmayacaktır.

Uygulama öncesindeki ikinci salt okunur incelemede OpenCode dosyası aynı konumda bulunamadı. KRCN bu dosyayı değiştirmemiştir ve henüz hiçbir istemci bootstrap yazması yapılmamıştır. Güvenilir bir yerel kopya bulunamadığı için gerçek apply adımı durduruldu. Mevcut içerik korunmuş gibi varsayılmayacak ve kullanıcının kararı olmadan boş içerikten yeni OpenCode dosyası oluşturulmayacaktır.

## Sonraki adım

Kod ve sözleşme commit edilip uzak CI doğrulanacaktır. Gerçek kullanıcı dosyası uygulaması, kaybolan OpenCode dosyasının geri getirilmesi veya boş durumdan yeniden oluşturulması için kullanıcı kararı alındıktan sonra yeni bir exact planla yapılacaktır.
