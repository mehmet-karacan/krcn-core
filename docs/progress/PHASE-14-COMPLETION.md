# Faz 14 Oracle metadata RAG tamamlandı

## Sonuç

KRCN Core, Oracle veri satırlarını almadan şema nesnelerini, program birimlerini, yapı bilgilerini ve bağımlılıkları proje kapsülünde sürümlü olarak yönetebilir. Yetkili JSON kayıtlarından project-scoped exact, full-text, vector ve graph indeksi üretilebilir.

## Hazırlanan yetenekler

- Oracle metadata için ayrı snapshot, object, immutable revision, dependency ve report modeli oluşturuldu.
- Varsayılan `select-compatible` toplama ile batch `OPEN/FETCH/CLOSE` yetki sınırı ayrıldı.
- Sabit metadata şablonları dışındaki serbest SQL reddediliyor.
- Kullanıcının `select-only`, `execute deny` ve diğer database kuralları korunuyor.
- Package specification ve package body ayrı nesne ve revizyon olarak saklanıyor.
- Değişmeyen nesne ve chunk kayıtları artımlı yenilemede yeniden üretilmiyor.
- Partial snapshot kayıp görünen nesneleri retired yapmıyor.
- Dependency kayıtları evidence kind, source view ve row digest provenance bilgisi taşıyor.
- Database link gibi hassas nesnelerin raw DDL metni saklanmıyor.
- Oracle metadata indeksi proje kapsülünde yeniden üretilebilir SQLite projeksiyonu olarak tutuluyor.

## Korunan sınırlar

- Uygulama tablosu satırı alınmaz.
- Serbest SQL, compile ve `ALTER SESSION` çalıştırılmaz.
- Secret, endpoint, wallet ve fiziksel bağlantı bilgisi kayıt veya indekse yazılmaz.
- Network bağlantısı ve remote embedding ayrı onay olmadan kullanılamaz.
- JSON metadata kayıtları yetkilidir; SQLite indeks yetkili kaynak değildir.
