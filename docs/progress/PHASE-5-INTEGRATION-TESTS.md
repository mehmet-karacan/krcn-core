# Faz 5 bütünleşik testleri

## Amaç

Faz 5 bileşenlerinin yalnız ayrı birimlerde değil, ortak application service, kalıcı runtime kayıtları ve farklı istemciler arasında birlikte çalıştığını doğrulamak.

## Geçen senaryolar

1. Doğal dil talebi ham metni kalıcılaştırmadan typed intent sözleşmesine dönüştürüldü.
2. Aynı intent, registry revision ve step girdileri bütün istemcilerde aynı task plan kimliğini üretti.
3. Salt okunur veri tabanı görevi açık `SELECT` policy kaydıyla authorization, worker ve verifier akışını tamamladı.
4. Kontrollü core etkisi gerçek dosyaya yazmadan exact mutation plan, worker effect ve verifier evidence zinciriyle doğrulandı.
5. User-data yazımı exact task plan, exact mutation plan, dry-run ve kullanıcı onayı olmadan reddedildi.
6. Kullanıcının `DELETE` yasağı, daha gevşek bir `allow` kuralı ve orchestrator onayı bulunsa bile etkili kaldı.
7. Remote provider isteği disclosure ve aynı session için exact kullanıcı onayı olmadan reddedildi.
8. Plan step kapsamı değiştiğinde eski plan kimliğiyle start işlemi reddedildi.
9. Worker kesintisi failed checkpoint olarak kaydedildi; yeni service örneği görevi sohbet geçmişi olmadan resume etti.
10. Yeni service örneğinde aynı idempotency kapsamıyla worker tamamlandı, verifier kanıtı geçti ve state completed oldu.
11. CLI, SDK, MCP, plugin, Codex ve Claude aynı application service kararlarını kullandı.
12. State, event, checkpoint ve handoff kayıtlarının yalnız geçici `.krcn` runtime alanında kaldığı doğrulandı.

## Paketleme doğrulaması

Repository wheel paketi ağ erişimi kapalıyken geçici hedefe kuruldu. Kurulu paketten intent, plan, authorization, worker, verifier, state ve ortak orchestrator servisleri yüklendi. Kaynak repository veya yerel referans dizini import edilmedi.

## Sınırlar

Testlerin tamamı sentetik içerik ve geçici dizinlerle çalıştı. Ağ bağlantısı kurulmadı. Gerçek kullanıcı verisi, canlı proje, gerçek entegrasyon, credential veya yerel referans kaynağı kullanılmadı. Kontrollü core senaryosu yalnız plan ve kanıt zincirini çalıştırdı; repository dosyasını değiştirmedi.
