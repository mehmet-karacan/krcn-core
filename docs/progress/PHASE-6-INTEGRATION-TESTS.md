# Faz 6 bütünleşik testleri

## Recovery senaryosu

Sentetik bir dış proje read-only onboarding ve discovery ile KRCN kullanıcı evine tanıtıldı. Kullanıcının database `DELETE` işlemini yasaklayan ve yalnız güvenli okuma davranışını koruyan policy kaydı source binding'e bağlandı.

Taşınabilir backup oluşturuldu, yeni ve boş kullanıcı evine restore edildi ve source binding beklendiği gibi `unbound` kaldı. Aynı proje içeriğinin yeni dizini read-only discovery ile doğrulanıp exact plan üzerinden rebind edildi.

## Kanıtlar

- Eski ve yeni dış proje dizinlerinin dosya digest ve zaman bilgileri değişmedi.
- Hiçbir proje dosyası KRCN kullanıcı evine kopyalanmadı.
- Fiziksel source locator backup içinde bulunmadı.
- Secret dizini restore edilmedi.
- Database `DELETE` deny policy restore sonrasında da etkin kaldı.
- Workspace, project, source binding ve derived discovery state korundu.

## Temiz clone ve update senaryosu

Yerel Git kaynağından temiz clone oluşturuldu. Clone içinde `.krcn` bulunmadığı doğrulandı. Repository verification ve doctor geçti. Faz 3 `merge into`, verification ve rollback regresyon testleri temiz clone üzerinde çalıştı. `git pull --ff-only` mevcut clone durumunu veri oluşturmadan doğruladı.

## Sonuç

`clone -> install/doctor -> restore -> rebind -> run` ve `pull -> merge into -> verify/rollback` davranışları aynı test paketinde doğrulandı.

