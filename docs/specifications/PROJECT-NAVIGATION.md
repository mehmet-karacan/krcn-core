# Project Navigation

## Amaç

Project Navigation, kayıtlı projeleri kullanıcıya numaralı ve salt okunur bir menü olarak sunar. Menü seçimi işlem yetkisi vermez ve hiçbir exact plan ya da kullanıcı onayı kapısını atlamaz.

## Proje listesi

`proje listesi`, `projelerim` ve `hangi projeler entegre` ifadeleri aşağıdaki güvenli özeti üretir:

- Sıra numarası, proje kimliği ve proje adı
- Kayıt ve entegrasyon durumu
- Aktif ve geçmiş talep sayıları
- Aktif ve geçmiş defect sayıları
- Aktif ve geçmiş görev sayıları
- Toplam iş sayısı
- En son güncelleme zamanı ve güncellemenin kapsamı

Son güncelleme zamanı, doğrulanmış yerel proje, entegrasyon, kaynak durumu, Work Item ve Work Documents kayıtlarının en yeni dosya değişiklik zamanıdır. Fiziksel dosya yolu açıklanmaz.

## Seçim

Projeler portable kimliğe göre sıralanır. Kullanıcı listeden `1` gibi bir numara seçtiğinde yalnız salt okunur `project resume` özeti açılır. Sonuç gerçek proje kimliğini taşır. Daha sonraki yazma işlemleri numarayı değil gerçek proje kimliğini, exact planı ve gerekli kullanıcı onayını kullanır.

Yanlış bir proje adı otomatik seçilmez. Sistem benzer kayıtları ve tam proje listesini göstererek kullanıcıdan numara ya da doğru ad bekler.

Seçilen proje görünümündeki işler aktiflik ve en son güncelleme zamanına göre sıralanır. Her işin son güncelleme zamanı gösterilir.
