# Faz 8 proje çalışma alanı istemci entegrasyonu

## Sonuç

Proje öğrenme akışı, proje bazlı KRCN çalışma alanı seçimiyle ortak application service düzeyinde birleştirildi. CLI, SDK, MCP, plugin, Codex, Claude ve gelecekteki istemciler aynı typed seçim ve initialization sözleşmesini kullanabiliyor.

## İlk kullanım akışı

1. `project.learn` veya doğal dilde proje öğrenme isteği proje kökünü çözümler.
2. Açık `data_root` veya `KRCN_HOME` yoksa `<proje-kökü>/.krcn` konumu kullanıcıya gösterilir.
3. Kullanıcı `use-default`, `choose-parent` veya `cancel` kararlarından birini verir.
4. Seçim hiçbir dizin oluşturmadan exact initialization planı üretir.
5. Plan kimliği ve açık onay eşleşirse Git koruması ile proje evi oluşturulur.
6. Sonraki öğrenme çalıştırması geçerli proje evini kullanır ve proje kaynağını yerinde, salt okunur inceler.

## Ortak servis işlemleri

- `project.home.resolve`: Salt okunur konum önerisi veya mevcut çözümleme üretir.
- `project.home.initialize`: Seçimi planlar, exact plan ve onayla uygular.
- `project.learn`: Başlatılmış proje evindeki ortak kayıtlara öğrenme planı üretir.

Taşıma katmanları karar üretmez. Yalnızca ortak yanıtı kullanıcıya veya çağıran araca gösterir.

## Korunan davranışlar

- Açık `data_root` ve `KRCN_HOME` akışları geriye dönük uyumlu kaldı.
- Seçim veya onay olmadan `.krcn` oluşturulmadı.
- Kaynak proje dosyaları kopyalanmadı veya değiştirilmedi.
- Geçerli proje evi manifesti doğrulanmadan proje içindeki veri kökü kullanılmadı.
- `.krcn` source identity ve discovery hesabına katılmadı.
- İstemci türü ek yetki sağlamadı.

## Doğrulama

Sentetik proje dizinleriyle şu durumlar test edildi:

- bütün istemcilerin aynı ilk kullanım seçimini alması;
- iptal kararının hiçbir dosya oluşturmaması;
- CLI üzerinde öneri, plan, exact apply ve sonraki proje öğrenme akışı;
- özel ana dizin seçiminin ortak servis üzerinden planlanıp uygulanması;
- proje kaynağı byte değerinin bütün akış boyunca değişmemesi;
- eski açık `data_root` kullanan proje öğrenme testlerinin değişmeden geçmesi.

Gerçek kullanıcı projesi, veritabanı veya belgesi test verisi olarak kullanılmadı.
