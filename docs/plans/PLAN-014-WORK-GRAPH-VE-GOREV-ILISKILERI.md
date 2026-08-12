# Plan 014 - Work Graph ve görev ilişkileri

## Durum

Bekliyor.

## Amaç

Talep, defect, görev, alt görev, karar, dosya, test, commit ve sürüm ilişkilerini proje bazlı kesin kayıtlar olarak saklamak.

## İş paketleri

1. Work item kimlik, durum, tür, revizyon ve provenance şemalarını oluştur.
2. Talep, defect, görev, alt görev ve karar kayıtlarını proje kapsülüne bağla.
3. Commit, branch, dosya, test ve release kanıtlarını Work Graph içine ekle.
4. Aktif, tamamlanmış, iptal edilmiş ve arşivlenmiş yaşam döngülerini tanımla.
5. İlişki bütünlüğünü ve döngü kontrollerini uygula.
6. `nerede kaldık`, aktif görevler ve geçmiş görevler sorgularını kesin kayıtlara bağla.
7. Görev tamamlandığında retrieval projeksiyonlarını güncelle.

## Kabul ölçütleri

- Bir değişikliğin hangi talep ve görev nedeniyle yapıldığı izlenebilir.
- Bir görevin commit, dosya ve test kanıtları kesin olarak bulunabilir.
- Görev durumu vektör benzerliğinden değil authoritative kayıttan okunur.
- Farklı AI istemcileri aynı devam bağlamını görür.
