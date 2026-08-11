# Faz 2 salt okunur discovery adapter'ı

## Amaç

Yerel bir source binding altındaki proje ve belge dosyalarını kaynak dizine yazmadan, fiziksel kök yolunu açığa çıkarmadan ve import sınırlarını aşmadan keşfetmek.

## Uygulanan davranış

1. Adapter yalnızca `local-path`, `read-only`, `read` ve `metadata` capability'lerine sahip binding kabul eder.
2. Kaynak kökün mutlak, mevcut ve sembolik bağlantı olmayan bir dizin olduğu doğrulanır.
3. Import politikasındaki engellenmiş yollar ve maksimum dosya boyutu uygulanır.
4. Dizin ve dosya sembolik bağlantıları takip edilmez.
5. Her kabul edilen dosya için göreli yol, tür, boyut ve SHA-256 kanıtı üretilir.
6. Hash sırasında değişen dosyalar sonuçtan çıkarılır.
7. Python, Node.js, Java, .NET, Go ve Rust teknoloji işaretleri yalnızca dosya adlarından belirlenir.
8. Sonuç fiziksel kaynak kökü veya dosya içeriği taşımaz.
9. Tüm dosya kanıtlarından deterministic kaynak digest'i üretilir.

## Atlanan içerik

Blocked, symlink, too-large, unstable ve unreadable sınıfları yalnızca sayaç olarak raporlanır. Engellenmiş dosya adı veya içeriği genel sonuca eklenmez.

## Doğrulama

Testler sentetik geçici kaynaklarda ağ kapalıyken çalıştırıldı. Tarama öncesi ve sonrası dosya içerikleri ile modification zamanları karşılaştırılarak kaynak dizinde değişiklik olmadığı doğrulandı.

## Sonraki adım

Discovery adapter'ı genel adapter capability sözleşmesine ve etkili kullanıcı policy zincirine bağlanacak.
