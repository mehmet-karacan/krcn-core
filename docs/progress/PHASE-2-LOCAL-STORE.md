# Faz 2 yerel kayıt deposu

## Amaç

Workspace, project ve source binding kayıtlarını core dosyalarından ayrı, user-data sahipliğinde ve güvenli güncelleme kurallarıyla saklamak.

## Uygulanan davranış

1. Her kayıt schema sürümü, kayıt türü, mantıksal kimlik, revision ve payload hash taşıyan bir envelope içinde saklanır.
2. Create ve update işlemleri önce deterministic mutasyon planı üretir.
3. Yazma için aynı plan kimliğine bağlı doğrulanmış dry-run ve kullanıcı onayı gerekir.
4. Beklenen revision değişmişse işlem uygulanmaz.
5. Dosya aynı dizindeki geçici dosyaya yazılır, diske aktarılır ve atomic replace ile etkinleştirilir.
6. Yazma sonrasında kayıt yeniden okunup revision ve payload hash doğrulanır.
7. Genel liste çıktısı payload veya fiziksel locator değeri içermez.
8. Sembolik bağlantı üzerinden kayıt yazımı reddedilir.

## Sahiplik

`.krcn/workspaces/**`, `.krcn/projects/**` ve `.krcn/source-bindings/**` user-data sınıfındadır. Core güncellemesi bu kayıtları değiştiremez veya varsayılan kayıtlarla ezemez.

## Doğrulama

Testler yalnızca geçici sentetik dizinlerde çalışır. Canlı kullanıcı verisi oluşturulmadı veya değiştirilmedi.

## Sonraki adım

Bu kayıt deposu kullanılarak kaynak dizine yazmayan, sentetik ve salt okunur proje onboarding akışı uygulanacak.
