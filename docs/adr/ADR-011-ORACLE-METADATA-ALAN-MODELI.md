# ADR 011: Oracle metadata ayrı bir alan modeli olarak saklanır

## Durum

Kabul edildi.

## Karar

Oracle metadata kayıtları genel knowledge belgelerine dönüştürülmez. Proje kapsülünde snapshot, object, immutable revision ve dependency kayıtları olarak saklanır. Arama ve vector yapısı bu kayıtların yeniden üretilebilir SQLite projeksiyonudur.

Varsayılan toplama `select-compatible` modundadır. Batch `OPEN/FETCH/CLOSE` akışı yalnız açık `execute` yetkisi ve ayrı onayla çalışabilir.

## Gerekçe

Oracle nesne kimliği, spec/body ayrımı, edition, structured schema alanları ve dependency provenance genel metin kaydından daha güçlü bir bütünlük modeli gerektirir. Ayrıca kullanıcının `select-only` ve `execute deny` kurallarının korunması, iki toplama modunun açıkça ayrılmasını gerektirir.

## Sonuçlar

- Satır verisi ve serbest SQL bu alanın dışında kalır.
- Değişmeyen nesneler yeniden revize veya vektörlenmez.
- Partial snapshot eksik nesneleri silmez.
- Secret içerebilen database link DDL kalıcılaştırılmaz.
- Metadata JSON kayıtları taşınabilir, fiziksel bağlantı bilgisi taşınamaz.
