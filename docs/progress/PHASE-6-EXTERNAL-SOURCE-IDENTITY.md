# Faz 6 dış proje kimliği ve kopyalamama garantisi

## Sonuç

Dış proje dizini ile KRCN kullanıcı evinin birbirinden tamamen ayrı olması makinece doğrulanabilir hale getirildi. Read-only discovery kanıtından fiziksel yol içermeyen taşınabilir bir source identity üretildi.

## Kimlik içeriği

- Mantıksal proje ve binding kimliği.
- `krcn-discovery-tree-sha256-v1` algoritması.
- Sıralı discovery kanıtının tree digest değeri.
- Kanıta giren dosya sayısı.

Kimlikte mutlak yol veya dosya içeriği bulunmaz.

## Korunan davranış

- Dış proje KRCN kullanıcı evinin içine yerleştirilemez.
- KRCN kullanıcı evi de dış projenin içine yerleştirilemez.
- Projeye identity marker yazılmaz.
- Kopyalama, taşıma, upload veya kaynak mutasyonu yapılmaz.
- Değişmiş digest eşleşmiş kabul edilmez; sistem tahmin yürütmez.

