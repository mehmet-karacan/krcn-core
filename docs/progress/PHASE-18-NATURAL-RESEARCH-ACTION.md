# Faz 18 Doğal Research Action

## Sonuç

Kullanıcıların araştırma altyapısının komutlarını ve tipli istek şemalarını bilme
zorunluluğu kaldırıldı. Codex, Claude Code, OpenCode ve doğrudan CLI aynı doğal dil
sınıflandırıcısını kullanır.

## Tamamlananlar

- `detaylı araştır`, `kök nedenini araştır`, `karşılaştır`, `araştır ve planla` ve
  İngilizce karşılıkları ortak politika üzerinden sınıflandırılır.
- Hızlı, standart, detaylı, karşılaştırmalı ve kök neden araştırma modları ayrılır.
- Yalnız araştırma, araştırma ve plan, araştırma ve uygulama hedefleri ayrılır.
- `bunu araştır` konuşma konusu varsa bu konuyu kullanır. Konu yoksa istek korunur ve
  yalnız eksik bağlam istenir.
- Genel `bunu yap` ifadesi sessizce araştırmaya çevrilmez.
- Aktif proje çalışma dizininden veya istek içindeki kayıtlı proje adından çözülür.
- Bilinmeyen veya birden çok proje sessizce global araştırmaya düşmez.
- `krcn ask` kısa insan çıktısı verir; JSON yalnız açıkça istendiğinde gösterilir.
- Natural Research Action mevcut V1A exact-plan hazırlığına bağlandı.
- Provider çağrısı, kaynak kod değişikliği veya uygulama yetkisi sınıflandırma sırasında
  verilmez.

## Dürüst yürütme sınırı

Proje araştırması hazırlandıktan sonra Work Item seçimi veya oluşturulması ve V1B rol
dispatch planı ayrıca hazırlanır. Global araştırma operatör aracılı veya mevcut istemci
araştırmasıyla devam eder. Bu dilim sahte biçimde `dispatch hazır` demez.

## Doğrulama

- Türkçe ve İngilizce niyet birim testleri geçti.
- Codex, Claude ve OpenCode aynı doğal istek için aynı exact planı üretti.
- Proje bağlamı, eksik konu, yanlış proje ve istemci çıktısı testleri geçti.
- Repository, JSON, bağlam ve tam regresyon kontrolleri başarıyla tamamlandı.
