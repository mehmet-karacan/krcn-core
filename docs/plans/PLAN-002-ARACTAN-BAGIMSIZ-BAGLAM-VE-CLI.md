# PLAN-002 - Araçtan bağımsız bağlam ve CLI baseline

## Durum

Bölüm 1 tamamlandı. Ortak context girişi, istemci adaptörleri, current-work işaretçisi ve context resolver hazırlandı. Çalışma Bölüm 2 - CLI davranış envanteri ile devam edecek.

## Amaç

KRCN Core deposunu açan Codex, Claude Code, başka bir yapay zekâ, IDE eklentisi, plugin veya otomasyonun aynı proje bağlamını kullanabilmesini sağlamak. CLI bu yapının tek giriş noktası olmayacak; yalnızca ortak core sözleşmesini kullanan istemcilerden biri olacak.

## Temel yaklaşım

Depoda tek bir kaynak doğrusu korunacak:

1. `AGENTS.md` davranış ve güvenlik kurallarının kaynağı olacak.
2. `AI-CONTEXT.md` araçtan bağımsız başlangıç ve yönlendirme belgesi olacak.
3. `.ai/repository-context.json` tüm istemciler için makinece okunabilir bağlam manifesti olacak.
4. `.ai/current-work.json` aktif planı, ilerleme kayıtlarını ve sonraki işlemleri gösterecek.
5. `CLAUDE.md` gibi istemci dosyaları ortak kaynakları içe aktaran ince adaptörler olarak kalacak.
6. CLI, plugin, MCP veya SDK adaptörleri aynı context resolver çıktısını kullanacak.

## Uygulama adımları

### Bölüm 1 - Context girişi

- Araçtan bağımsız başlangıç belgesini oluştur.
- Repository context ve current-work şemalarını oluştur.
- Codex ve Claude Code girişlerini ortak kaynak doğrusuna bağla.
- Göreli yolları çözen ve bağlam özetini üreten resolver ekle.
- Bağlamın istemciye göre farklılaşmadığını test et.

### Bölüm 2 - CLI davranış envanteri

- Mevcut komutları salt okunur, mutasyon yapan ve ağ kullanabilen gruplara ayır.
- Her komutun core, runtime, user-data, derived ve secrets etkisini kaydet.
- Otomatik provider keşfi ve makineye özel yol bağımlılıklarını belirle.
- Korunacak mevcut davranışlar için kabul testleri yaz.

### Bölüm 3 - Arındırılmış CLI staging

- Monolitik CLI'ı Git dışındaki staging alanına al.
- Context resolver kullanımını ortak giriş noktası yap.
- Fiziksel proje yollarını source binding katmanına taşı.
- Varsayılan ağı kapat ve provider kullanımını açık onaya bağla.
- Mutasyonları sahiplik ve dry-run kontrolüne bağla.
- Kullanıcı onayından sonra takip edilen depo ağacına aktar.

## Kabul ölçütleri

- Codex `AGENTS.md` üzerinden ortak kuralları bulmalı.
- Claude Code `CLAUDE.md` üzerinden aynı kuralları ve başlangıç bağlamını içe aktarmalı.
- Başka bir istemci yalnızca `AI-CONTEXT.md` veya repository context manifestiyle projeyi anlayabilmeli.
- Aktif plan ve son ilerleme bilgisi istemci dosyalarına kopyalanmamalı.
- Resolver yalnızca göreli depo yolları üretmeli.
- Context çözümleme ağ erişimi ve harici Python bağımlılığı gerektirmemeli.
- Yerel kaynak yolları, kullanıcı verisi ve secret değerleri context çıktısına girmemeli.
- Tüm testler ve foundation doğrulaması geçmeli.

## Onay kapısı

Context altyapısı yeni ve taşınabilir core kodu olarak doğrudan geliştirilebilir. Eski CLI kaynaklarının takip edilen depo ağacına aktarılması, ayrı staging incelemesi ve kullanıcı onayı gerektirir.
