# Faz 7 büyük proje discovery düzeltmesi

## Gerçek test bulgusu

Çok modüllü gerçek bir proje üzerinde yapılan ilk `project.learn` dry-run işlemi, generated dependency ve build ağaçları nedeniyle 10.000 dosyalık güvenlik sınırında durdu. Dosya sayısının büyük bölümü `node_modules`, `.next` ve `target` dizinlerinden geliyordu.

## Düzeltme

Import ve discovery politikası aşağıdaki standart generated dizinleri traversal başlamadan engelleyecek şekilde genişletildi:

- `node_modules`
- `.next`
- `target`
- `dist`
- `build`
- `coverage`
- `logs`

Dosya limiti yükseltilmedi. Böylece güvenlik sınırı korunurken kaynak kodla ilgisi olmayan bağımlılık, build, coverage ve log ağaçları hash işlemine alınmıyor.

## Regresyon kanıtı

Sentetik test generated ağaçlarına limitin üzerinde dosya yerleştiriyor. Discovery bu dizinleri tek tek dosya saymadan buduyor, yalnız proje kaynaklarını kaydediyor ve mevcut file limit davranışını koruyor.
