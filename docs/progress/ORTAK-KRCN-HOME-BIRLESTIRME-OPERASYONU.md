# Ortak KRCN Home Birleştirme Operasyonu

## Durum

`portability.merge-project-home` operasyonu geliştirildi. Operasyon, boş olmayan bir ortak kullanıcı veri köküne yalnızca eksik user-data kayıtlarını eklemek üzere exact plan üretir.

## Tamamlanan güvenlik sınırları

- Kaynak ve hedef için ayrı secret-safe yedek planlanır.
- Her iki yedek yazılıp doğrulanmadan hedef kaydı eklenmez.
- Aynı göreli yolda farklı içerik varsa işlem yazma öncesinde durur.
- Kaynak `.krcn` korunur ve hiçbir kaynak proje dosyası kopyalanmaz.
- Hedefteki mevcut dosyalar değiştirilmez, taşınmaz veya silinmez.
- Project-home manifesti, runtime, derived, local-data ve secret alanları birleşmeye alınmaz.
- Public plan fiziksel kaynak ve KRCN home yollarını açıklamaz.
- Stale plan ve eksik exact-plan onayı reddedilir.
- CLI, SDK, MCP, plugin ve AI istemcileri aynı application service planını kullanır.

## Doğrulama

- Birim ve istemci eşitliği testleri geçti.
- Repository güvenlik ve belge denetimi geçti.
- Gerçek `gpu-fusion` kaynağı ve ortak hedef üzerinde salt okunur dry-run başarıyla tamamlandı.
- Dry-run dört user-data kaydı belirledi: workspace, project, source binding ve integration.
- Hedefteki mevcut staging içeriğine yönelik hiçbir mutation planlanmadı.

## Sonraki adım

Operasyon commit ve uzak CI doğrulamasından sonra onaylanan exact plan ile gerçek kayıtlara uygulanacaktır. Ardından derived source state hedefte yeniden üretilecek ve ortak `KRCN_HOME` erişimi iki çalışma dizininden doğrulanacaktır.
