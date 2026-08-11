# ADR-004 - Araçtan bağımsız repository bağlamı

## Durum

Kabul edildi.

## Bağlam

KRCN Core yalnızca kendi CLI'ı tarafından kullanılmayacak. Codex, Claude Code, IDE eklentileri, plugin'ler ve ileride eklenecek MCP veya SDK adaptörleri aynı projeyi ve aktif geliştirme durumunu anlayabilmeli.

Her istemci için ayrı ve kapsamlı talimat dosyası tutulması zamanla çelişen kurallar, eski plan bilgileri ve farklı güvenlik sınırları üretir. Yalnızca CLI üzerinden bağlam sunmak ise dosya okuyabilen ancak CLI çalıştırmayan istemcileri dışarıda bırakır.

## Karar

1. Davranış kurallarının tek kaynak doğrusu `AGENTS.md` olacak.
2. Araçtan bağımsız yönlendirme `AI-CONTEXT.md` ile sağlanacak.
3. Makinece okunabilir yönlendirme `.ai/repository-context.json` içinde tutulacak.
4. Aktif geliştirme durumu `.ai/current-work.json` üzerinden çözülecek.
5. Claude Code için `CLAUDE.md`, ortak dosyaları içe aktaran ince bir adaptör olacak.
6. Diğer istemci adaptörleri iş kuralı kopyalamayacak; ortak manifesti okuyacak veya context resolver kullanacak.
7. Context resolver ağ kullanmayacak ve yalnızca depo içindeki göreli yolları kabul edecek.

## Sonuçlar

- Yeni bir yapay zekâ veya plugin, özel bir KRCN Core istemcisi yazılmadan bağlamı okuyabilecek.
- Plan ve ilerleme değişiklikleri tek current-work kaydından takip edilecek.
- İstemciye özel dosyalar küçük kalacak ve bağlam penceresini gereksiz yere tüketmeyecek.
- Talimat dosyaları güvenlik politikalarını hatırlatır ancak teknik yetki kontrolünün yerini almaz.
