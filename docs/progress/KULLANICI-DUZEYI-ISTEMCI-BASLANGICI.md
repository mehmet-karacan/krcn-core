# Kullanıcı Düzeyi İstemci Başlangıcı

## Durum

Codex, Claude Code ve OpenCode için ortak `client.bootstrap` operasyonu geliştirildi, gerçek kullanıcı ortamına uygulandı ve doğrulandı.

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

- Kullanıcı, ilk incelemede görülen OpenCode dosyasını kendisinin sildiğini doğruladı.
- Boş Codex kullanıcı yönerge dosyası yazma öncesinde yedeklendi.
- Eksik Claude Code ve OpenCode kullanıcı yönerge dosyaları oluşturuldu.
- Üç istemci dosyasında da yalnızca aynı yönetilen KRCN başlangıç bloğu bulunur.
- Her dosyada bir başlangıç ve bir bitiş işareti bulunduğu doğrulandı.
- Üç dosyanın içerik hash değerlerinin aynı olduğu doğrulandı.
- Kurulum ikinci kez planlandığında değişiklik ve etki üretmedi.

Kullanıcı dosyaları, yedekler ve fiziksel yollar Git'e eklenmedi.

## Uçtan uca doğrulama

- Global `krcn` komutu proje kökünden çalıştırıldı.
- Proje çalışma dizininden doğru kayıtla eşleşti.
- Ortak KRCN home içindeki kaynak durumu yüklendi.
- Kaynak durumunda 1.752 dosya ile Java ve Node.js teknolojileri görüldü.
- Proje kaynakları yerinde ve salt okunur bağlı kaldı.

Yeni Codex, Claude Code veya OpenCode oturumları kullanıcı düzeyindeki bu başlangıç talimatını yükler. İstemci önce `krcn project current` veya `krcn project resume` ile ortak bağlamı çözümler; eşleşme yoksa normal çalışmaya devam eder.
