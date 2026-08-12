# İlk entegrasyon CLI başlangıcı

## Durum

Tamamlandı.

## Amaç

Kullanıcının ilk proje isteğinde yalnız `Bu projeyi entegre et` demesini yeterli hale getirmek, global KRCN CLI eksikse kurulum planını güvenli biçimde araya almak ve ilk isteği kaybetmeden entegrasyona devam etmek.

## Tamamlanan çalışmalar

1. İlk kullanım davranışı ortak `intent-routing` sözleşmesine eklendi.
2. Kurulum öncesi etki gösterimi ve açık onay zorunluluğu korundu.
3. Bekleyen proje dizini ve entegrasyon isteğinin kurulum sonrasında devam ettirilmesi istemci kurallarına bağlandı.
4. Windows kurucusu korunurken macOS ve Linux için izole yerel Python ortamı eklendi.
5. POSIX shell profile dosyalarında yalnız işaretli KRCN bloğunun yönetilmesi sağlandı.
6. Mevcut shell profile içeriği, dosya modu ve KRCN_HOME ayrımı korundu.
7. CLI kurulumu, istemci bootstrap işlemi, proje çalışma alanı ve proje entegrasyonu ayrı onay sınırlarında bırakıldı.

## Doğrulama

- Kurulum planı bütün platformlarda değişiklik yapmadan çalışıyor.
- POSIX managed block ekleme, güncelleme, bozuk marker reddi ve atomik yazma testleri bulunuyor.
- Doğal dil first-use policy sözleşmesi test ediliyor.
- Codex, Claude Code ve OpenCode istemci bootstrap testleri ilk isteği sürdürme kuralını taşıyor.

## Korunan alanlar

- Dış proje kaynakları okunmadı veya değiştirilmedi.
- KRCN_HOME oluşturulmadı, taşınmadı veya seçilmedi.
- Kullanıcı policy ve secret kayıtları değiştirilmedi.
- Mevcut istemci ve shell profile içerikleri yönetilen blok dışında korunuyor.
