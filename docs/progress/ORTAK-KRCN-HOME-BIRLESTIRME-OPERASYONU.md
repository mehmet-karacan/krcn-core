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

## Gerçek veri uygulaması

Onaylanan exact plan, `gpu-fusion` proje evinden ortak kullanıcı veri köküne başarıyla uygulandı.

- Workspace, project, source binding ve integration olmak üzere dört user-data kaydı eklendi.
- Kaynak ve hedef için iki ayrı secret-safe yedek oluşturuldu ve doğrulandı.
- Kaynak evin bütün dosyaları işlem öncesi hash değerleriyle aynı kaldı.
- Hedefte birleşme öncesinde bulunan bütün dosyalar işlem öncesi hash değerleriyle aynı kaldı.
- Derived source state ortak kullanıcı veri kökünde yeniden üretildi.
- Yeniden üretim 1752 kaynak kaydı, Java ve Node.js teknolojileri ile tutarlı bir root digest verdi.
- Hem proje kökünden hem KRCN Core kökünden aynı `gpu-fusion` projesi ve source state okundu.
- Kullanıcı düzeyindeki `KRCN_HOME` onaylanan ortak veri köküne ayarlandı.
- `.krcn` altında Git tarafından izlenen dosya sayısı sıfır olarak doğrulandı.

## Sonraki adım

Çalışma dizinine göre otomatik proje eşleştirme, `Nerede kaldık?` özeti ve Codex, Claude Code ile OpenCode için kullanıcı düzeyindeki başlangıç bağlantıları geliştirilecektir.
