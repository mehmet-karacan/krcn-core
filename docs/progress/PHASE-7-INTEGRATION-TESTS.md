# Faz 7 bütünleşik testleri

## Sonuç

Doğal dil ile proje öğrenme akışı sentetik ve dışarıda duran bir proje dizini üzerinde uçtan uca doğrulandı.

## Doğrulanan senaryo

1. Kullanıcı yalnız doğal dil isteği içinde proje dizinini verdi.
2. Sistem görünen adı ve üç teknik kimliği otomatik çıkardı.
3. Dry-run dört kayıt içeren exact planı üretti.
4. Tek approval ile source binding, project, workspace ve source state kayıtları oluşturuldu.
5. Kaynak proje byte, boyut ve zaman bilgileri değişmedi.
6. Kaynak dosya içeriği KRCN kullanıcı evine kopyalanmadı.
7. Önceden var olan database select-only policy byte düzeyinde korundu ve delete kararı deny olarak kaldı.
8. Aynı fiziksel dizinin ikinci kez tanıtılması engellendi.

Test yalnız geçici sentetik dizinleri kullandı. Gerçek kullanıcı verisi, gerçek proje veya yerel referans kaynağı değiştirilmedi.
