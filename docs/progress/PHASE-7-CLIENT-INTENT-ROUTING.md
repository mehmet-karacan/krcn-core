# Faz 7 istemci intent yönlendirmesi

## Sonuç

Codex, Claude, MCP, SDK, plugin, generic AI ve CLI istemcilerinin proje öğrenme taleplerini aynı `project.learn` operation değerine yönlendirmesi için canonical sözleşme oluşturuldu.

## Canonical kaynaklar

- `config/intent-routing.json` desteklenen intent terimlerini, gereken tek girdiyi ve güvenlik sınırlarını tanımlar.
- `schemas/intent-routing.schema.json` bu route kaydının biçimini sınırlar.
- `AGENTS.md` repository içinde çalışan agent davranışını tanımlar.
- `AI-CONTEXT.md` generic AI ve plugin istemcileri için aynı yönlendirmeyi açıklar.

## İstemci davranışı

- Yalnızca var olan yerel proje dizini zorunludur.
- Teknik kimlikler ve görünen ad shared service tarafından çıkarılır.
- İstemciler kendi phrase listelerini veya inference kurallarını oluşturmaz.
- Kaynak yerinde ve salt okunur incelenir.
- Exact plan gösterilmeden user-data mutation yapılmaz.
- Proje dosyaları core repository'ye veya KRCN kullanıcı evine kopyalanmaz.

Bu sözleşmeyi okuyan yeni bir istemci provider-specific ürün kuralı eklemeden aynı service operation değerini kullanabilir.
