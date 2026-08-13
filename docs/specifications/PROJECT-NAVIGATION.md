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

Doğal dilde `krcn ask "proje listesi"` ve doğrudan `krcn project list` komutları listeyi varsayılan olarak tablo biçiminde gösterir. Tablo talep, defect ve görev sayılarını `aktif/geçmiş` biçiminde sunar. İstemciler ve otomasyonlar yapılandırılmış sonucu `--format json` seçeneğiyle alır.

## İş listeleri

Bir proje için görev, talep veya defect listesi hem doğal dille hem doğrudan CLI komutuyla alınabilir:

```powershell
krcn ask "gpu-fusion görev listesi"
krcn ask "gpu-fusion aktif talepler"
krcn ask "gpu-fusion geçmiş defectler"
krcn work list --project gpu-fusion --type task
```

Bir projenin kayıtlı kaynak dizinindeyken `--project` verilmeden `krcn work list --type defect` kullanılabilir. Liste varsayılan olarak tablodur; `--format json` yapılandırılmış sonucu korur. `--status active`, `--status historical` ve `--limit` filtreleri salt okunurdur ve işlem yetkisi vermez.

## Seçim

Projeler portable kimliğe göre sıralanır. Kullanıcı listeden `1` gibi bir numara seçtiğinde yalnız salt okunur `project resume` özeti açılır. Sonuç gerçek proje kimliğini taşır. Daha sonraki yazma işlemleri numarayı değil gerçek proje kimliğini, exact planı ve gerekli kullanıcı onayını kullanır.

Yanlış bir proje adı otomatik seçilmez. Sistem benzer kayıtları ve tam proje listesini göstererek kullanıcıdan numara ya da doğru ad bekler.

Seçilen proje görünümündeki işler aktiflik ve en son güncelleme zamanına göre sıralanır. Her işin son güncelleme zamanı gösterilir.
