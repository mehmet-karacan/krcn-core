# Unified retrieval

## Amaç

Birleşik retrieval, Work Graph, revision-aware knowledge, kaynak kod ve Oracle metadata sonuçlarını tek açıklanabilir proje sorgusunda toplar. Bu katman yetkili kayıtların yerine geçmez. Her sonuç domain, authority, revision veya digest, evidence reference ve skor açıklaması taşır.

## Sorgu sırası

1. Proje ve kapsam kesinleştirilir.
2. Resume, status, history ve görev soruları `status` niyetine yönlendirilir ve yetkili Work Graph kayıtlarından alınır.
3. Exact kimlik ve kayıt eşleşmeleri değerlendirilir.
4. Geçerli full-text ve yerel vector indeksleri çalıştırılır.
5. Dependency graph kanıtı eklenir.
6. Authority sınıfı ve freshness ile yeniden sıralanır.
7. Hit ve token bütçesi uygulanır.

Semantic benzerlik exact veya authoritative kanıtı geçemez. Vektör sonucu tek başına görev durumunu, kullanıcı politikasını veya proje gerçeğini belirleyemez.

## Kapsam

Varsayılan sorgu kapsamı tek projedir. Birden fazla proje yalnız request içinde açık project listesi ve `multi-project` scope ile seçilebilir. Sonuçlar project id taşır ve projeler arası karışma oluşturmaz.

## Domain davranışı

- `work`: Görev, talep, defect, karar, kanıt, commit ve geçmiş. Yetkili JSON kaydı kullanır.
- `knowledge`: Authoritative source, knowledge ve approved memory. Revision-aware catalog ve hybrid index kullanır.
- `code`: Kayıtlı dış projeyi yerinde okur. Stale source digest aramayı durdurur.
- `oracle`: Yetkili Oracle object/revision JSON kayıtları ile proje SQLite indeksini kullanır. Satır verisi içermez.

## Freshness ve kurtarma

Eksik, stale, kurcalanmış veya bozuk indeks sessizce kullanılamaz. Application service response içindeki domain durumu `blocked-stale` veya `unavailable` olur ve rebuild ya da project integration için açık next action döndürür. Başka domain sonuçları güvenliyse kısmi sonuç üretilebilir; response bu eksikliği bildirir.

## Provider sınırı

Birleşik retrieval kendiliğinden uzak provider çağırmaz. Remote semantic scoring yalnız mevcut provider request, disclosure ve session approval kapısından geçebilir. Onay yoksa yerel deterministic profil kullanılır veya remote domain sonucu atlanır.

## Bağlam paketi

Seçilen hit'ler, mantıksal source reference ve digest kanıtıyla context candidate haline getirilebilir. Fiziksel proje yolu, secret, bağlantı değeri ve ham worker girdisi sonuç içine alınmaz.
