# Faz 3 başlangıcı

## Başlangıç baseline'ı

Faz 3, tamamlanmış Faz 2 baseline'ının bulunduğu `cce08b7` commiti üzerinden başlatıldı. Çalışma dizini temiz ve `main` ile `origin/main` aynı durumdaydı.

## Hedef

Mevcut bir KRCN Core kurulumuna yeni release'i kullanıcı verisini bozmadan uygulayan inspection, diff, dry-run, backup, merge, migration, verify ve rollback motorunu tamamlamak.

## İlk sözleşmeler

1. Release kimliği, sürüm uyumluluğu, source commit ve managed file işlemleri makinece tanımlandı.
2. Upsert payload'ları SHA-256 ve byte boyutuyla bağlandı.
3. Delete işlemi önceki managed hash kanıtına bağlandı.
4. Migration ve derived action kimlikleri manifestte veri olarak tutuldu; manifest içeriği komut olarak çalıştırılmayacak.
5. Installation state aktif release, managed file hashleri, schema sürümleri, tamamlanan migration'lar ve bekleyen derived action'ları taşıyacak.
6. Manifest ve state içindeki yollar göreli ve taşınabilir olacak.
7. Fiziksel installation veya release dizini versioned kayıtlara girmeyecek.

## Koruma kararı

Faz 3 geliştirmesi gerçek kurulumda çalıştırılmayacak. Apply, migration, derived ve rollback testleri yalnızca geçici sentetik dizinlerde yürütülecek. Canlı user-data veya yerel referans kaynakları bu fazın geliştirme girdisi değildir.

## Sonraki adım

Installation state ve gerçek dosya durumunu salt okunur karşılaştıran, sahiplik sayımlarını ve kesintiye uğramış deployment kayıtlarını fiziksel yol göstermeden raporlayan inspection servisi oluşturulacak.
