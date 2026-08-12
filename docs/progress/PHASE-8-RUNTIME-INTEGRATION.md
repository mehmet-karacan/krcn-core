# Faz 8 çalışma bileşenleri ve salt okunur entegrasyon

## Sonuç

Skill, adapter, secret provider, worker ve verifier çalışma bileşenleri tek bir açık kayıt modeli altında birleştirildi. Bileşenler host veya plugin taramasıyla keşfedilmiyor; her biri versioned capability kayıtlarına ve izin verilen yan etkilere bağlanıyor.

Gerçek SQLite bağlantısı kullanan salt okunur referans akışı tamamlandı. Akış integration kaydı, source binding, kullanıcı policy'si, capability seçimi, secret reference, adapter gate, worker ve verifier kontrollerinin tamamından geçiyor.

## Korunan sınırlar

1. `SELECT` dışındaki işlemler policy ve SQL sınıflandırma katmanlarında reddediliyor.
2. SQLite bağlantısı yalnız `mode=ro` URI ve `query_only` çalışma modu ile açılıyor.
3. Sonuç satırları, veritabanı yolu ve secret değeri public yanıta girmiyor.
4. Secret dosyaları Git'e, loglara veya normal backup paketine eklenmiyor.
5. CLI, SDK, MCP, plugin, Codex ve Claude istemcileri aynı application service kararını kullanıyor.
6. Harici proje veya veritabanı dosyası KRCN Core içine kopyalanmıyor.

## Doğrulama

Sentetik bir SQLite veritabanı üzerinde başarılı sorgu, farklı istemci eşitliği, `DELETE` reddi, eksik secret, satır limiti, veri değişmezliği ve public çıktı maskelemesi test edildi. Hedefli test kümesindeki 35 test ve 20 alt test geçti.

Bir sonraki adım, yerel SQLite FTS ve vektör temsillerini kullanan ölçülebilir hibrit RAG katmanıdır.
