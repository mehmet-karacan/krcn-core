# Faz 5 orchestration state, resume ve handoff

## Amaç

Orchestrator bağlamını sohbet geçmişinden ve belirli bir istemciden bağımsız hale getirmek; state, event, checkpoint ve handoff kayıtlarını yerel runtime alanında güvenle sürdürmek.

## Tamamlananlar

1. Orchestration state için revision ve digest kontrollü durum makinesi oluşturuldu.
2. Her geçiş önceki event digest değerine bağlı append-only event kaydı üretti.
3. Event zinciri sequence, prior digest ve state revision üzerinden resume sırasında yeniden doğrulandı.
4. Worker checkpoint ve effect journal kayıtları runtime sahipliğindeki ayrı koleksiyona alındı.
5. Başarısız checkpoint aynı step kaydında yeni revision ile güvenli biçimde güncellenebilir hale getirildi.
6. Resume akışı tamamlanan worker adımlarını ve sıradaki çalışabilir adımları dependency bilgisiyle yeniden kurdu.
7. Awaiting-approval state, birebir plan approval trigger listesini handoff paketinde korudu.
8. Handoff paketi state digest, event head, tamamlanan ve bekleyen adımlar, hata kodları ve canonical context referanslarını taşıdı.
9. Handoff içine ham kullanıcı talebi, sohbet geçmişi veya kaynak içerik alınmadı.
10. `completed` geçişi yalnız başarılı ve aynı plan ile authorization kaydına bağlı task verification sonucuyla mümkün oldu.

## Yerel kayıt alanları

- `.krcn/runtime/orchestration-states/**`
- `.krcn/events/orchestration/**`
- `.krcn/checkpoints/orchestration/**`
- `.krcn/runtime/orchestration-handoffs/**`

Bu alanların tamamı ownership manifestinde `runtime` sınıfındadır, Git tarafından taşınmaz ve core güncellemesinde korunur. Runtime yazımı exact mutation plan ve dry-run doğrulamasından geçer; user-data onayı üretmez veya kullanıcı politikalarını değiştirmez.

## Doğrulama

- Authorized başlangıçtan running, verifying ve completed durumlarına tam event zinciriyle geçildi.
- Kaydedilmiş checkpoint başka bir süreçte doğrulanarak resume edildi.
- Kesilen görev sohbet geçmişi olmadan sıradaki worker adımıyla yeniden kuruldu.
- Başarısız verification ile completed geçişi reddedildi.
- Event kaydı değiştirildiğinde payload ve zincir doğrulaması fail-closed sonuç verdi.
- Runtime sahipliği ve onaysız user-data mutasyonu yapılmadığı doğrulandı.
- Dört yeni şema ve tüm depo testleri doğrulandı.

## Sonraki adım

Orchestrator akışını ortak uygulama servisine bağlamak ve CLI, SDK, MCP, plugin, Codex ile Claude istemcilerinin aynı kuralları kullanmasını sağlamak.
