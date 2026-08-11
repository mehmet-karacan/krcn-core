# Faz 6 dış proje yeniden bağlama

## Sonuç

Bilgisayar veya proje yolu değiştiğinde dış proje dizinini kopyalamadan yeniden tanıtan `project.rebind` akışı oluşturuldu.

## Akış

1. Mevcut source binding ve son kabul edilmiş discovery state okunur.
2. Kullanıcının seçtiği yeni dizin salt okunur discovery ile incelenir.
3. Path-independent source identity birebir karşılaştırılır.
4. Eşleşen locator ve derived binding revision için exact plan üretilir.
5. User-data yazımı açık approval olmadan uygulanmaz.
6. Apply öncesinde aday kimliği yeniden doğrulanır.

## Güvenlik sonucu

- Aday path public summary içine girmez.
- Eski veya yeni proje dizinine yazılmaz.
- Proje dosyası KRCN kullanıcı evine kopyalanmaz.
- Kimlik uyuşmazsa sistem başka bir dizini tahmin etmez ve kayıt değişmez.
- Eksik proje kaydı silinmez; rebind tamamlanana kadar korunur.

