# Faz 10 kaynak kod RAG indeksi tamamlandı

## Sonuç

`Projeyi entegre et` akışı artık proje bilgi kayıtlarına ek olarak gerçek kaynak kod için ayrı ve artımlı bir RAG indeksi hazırlıyor. Kullanıcının ayrıca `vektörle` demesi gerekmiyor. Eksik veya güncel olmayan kaynak kod indeksi aynı exact plan içinde görünür hale geliyor ve açık onaydan sonra uygulanıyor.

## İndeks yapısı

- Desteklenen kaynak ve yapılandırma dosyaları kayıtlı salt okunur binding üzerinden yerinde okunur.
- Parçalar göreli dosya yolu, dil, kesin satır ve karakter aralığı, dosya ve parça hash'i, güvenli semboller ve 192 boyutlu yerel vektör taşır.
- Ham kaynak metni ve fiziksel proje kökü SQLite içinde saklanmaz.
- Değişmeyen dosyaların doğrulanmış parçaları tekrar kullanılır.
- Değişen ve eklenen dosyalar yeniden işlenir, silinen dosyalar indeksten çıkarılır.
- İndeks staging alanında hazırlanır, SQLite bütünlük denetiminden geçirilir ve atomik olarak değiştirilir.

## Arama davranışı

`project.search-source-code` sınıf, metot, sembol, yol ve doğal dil sorgularını göreli yol ve satır kanıtıyla döndürür. Kod içeriği istendiğinde seçilen parça gerçek proje dosyasından okunur. Dosya ve parça hash'leri indeksle uyuşmuyorsa sonuç döndürülmez ve yeniden entegrasyon istenir.

İndeksin dosya veya vektör kayıtları sonradan değiştirilirse saklanan indeks kimliğiyle uyuşmazlık oluşur. Sağlık özeti ve arama bu durumu güvenilir kabul etmez.

## Proje yaşam döngüsü

- `project.integrate`, kaynak kod indeksini tam entegrasyonun zorunlu aşamalarından biri olarak yönetir.
- Yalnız indeks eksikse güncel discovery kanıtı kullanılır ve gereksiz kaynak taraması yapılmaz.
- `project.index-source-code`, kayıtlı bir projede doğrudan bakım ve yenileme planı sunar.
- `project.search-source-code`, tüm istemcilerin kullandığı ortak application servisi üzerinden çalışır.
- `project.resume`, indeks durumu, dosya ve parça sayısı ile güncellik bilgisini kalıcı bağlama ekler.
- CLI, Codex, Claude Code, OpenCode, plugin, MCP ve SDK aynı ürün sözleşmesine yönlendirilir.

## Gerçek proje doğrulaması

`gpu-fusion` üzerinde gerçek kaynak kod indeksi oluşturuldu ve doğrulandı:

- 1.726 desteklenen dosya indekslendi.
- 3.020 kaynak kod parçası üretildi.
- 14.176.256 baytlık içeriksiz SQLite indeks oluşturuldu.
- `AuditHistoryService` araması Java servis dosyasını doğru göreli yol ve satır aralıklarıyla ilk sonuçlarda döndürdü.
- Seçilen kod parçaları gerçek dosyadan hash doğrulamasıyla okundu.
- Ham kaynak örneği ve fiziksel proje yolu SQLite baytlarında bulunmadı.
- Kaynak proje dosyaları KRCN tarafından değiştirilmedi.
- Hemen sonraki otomatik entegrasyon denetimi no-op oldu.

Dosya ve parça sayıları doğrulama anındaki proje durumunun kanıtıdır. Kaynak değiştikçe sonraki entegrasyon bunları artımlı olarak günceller.

## Sağlayıcı sınırı

Varsayılan indeks tamamen yerel `deterministic-hashing` profiliyle ve 192 boyutlu vektörlerle çalışır. Qwen3 Embedding ve BGE-M3 alternatifleri katalogda tutulur. Gerçek proje kodu ayrı provider planı ve açık session onayı olmadan uzak embedding servisine gönderilmez.

## Korunan sınırlar

- Proje kaynakları KRCN Core veya KRCN home içine kopyalanmadı.
- Proje kaynakları indeksleme sırasında değiştirilmedi.
- Ham kaynak kod ve fiziksel proje yolu kalıcı indekse yazılmadı.
- Kullanıcı verisi exact plan ve açık onay olmadan değiştirilmedi.
- Uzak provider örtük olarak kullanılmadı.
- Eski veya kurcalanmış indeks yanlış sonuç vermek yerine kapalı biçimde reddedildi.
