# KRCN Core

KRCN Core; projeleri, belgeleri, işleri ve talepleri, kararları, kalıcı bağlamı ve belleği ortak bir çekirdeğe bağlayan yerel öncelikli bir platformdur.

KRCN Core'un temel yaklaşımı ve özgün mimarisi Mehmet KARACAN tarafından oluşturulmuştur. Proje, bu mimari vizyonu sürdürülebilir ve geliştirilebilir bir açık teknik yapıya dönüştürmek amacıyla yürütülmektedir.

## Temel hedef

Kullanıcı bir CLI'a veya yapay zekâya hedefini doğal dille anlatır. Sistem gerekli görev tanımını, kaynak ilişkilerini, bağlamı, güvenlik sınırlarını ve doğrulama adımlarını üretir. Bunu yaparken mevcut kullanıcı verisini korur ve yalnızca kontrollü core güncellemeleri uygular.

## Güncelleme ilkesi

Git'ten gelen yeni core sürümünde aşağıdaki işlemler uygulanır:

1. Mevcut kurulum ve veri sahipliği incelenir.
2. Değişiklikler `dry-run` olarak gösterilir.
3. Kullanıcı verisi ve yerel secret'lar korunur.
4. Gerekiyorsa şema migration'ı ve türetilmiş indekslerin yeniden oluşturulması planlanır.
5. Güncelleme, yedekleme ve uyumluluk kontrollerinden sonra uygulanır.
6. Doğrulama başarısız olursa güvenli rollback sunulur.

## Güncel geliştirme durumu

Repository foundation, sahiplik sınırları ve ilk core sözleşmeleriyle çalışır durumdadır. Yerel referans kaynaklarındaki kullanıcı verileri içeri alınmamıştır. Generic sözleşmeler arındırılarak JSON tabanlı core tanımlarına dönüştürülmüştür.

Kök çalışma kuralları için `AGENTS.md`, araçtan bağımsız başlangıç bağlamı için `AI-CONTEXT.md` dosyasını okuyun. Codex doğrudan `AGENTS.md` kullanır. Claude Code için `CLAUDE.md` aynı ortak kaynakları içe aktarır. Diğer istemciler ve plugin'ler `.ai/repository-context.json` manifestini okuyabilir.

Geliştirme sırası `docs/plans/ROADMAP.md`, güncelleme güvenlik sözleşmesi `docs/specifications/UPDATE-MERGE-CONTRACT.md` içindedir. Mevcut baseline bulguları `docs/progress/PHASE-0-BASELINE.md`, aktarım sınırı ise `docs/specifications/IMPORT-BOUNDARY.md` içinde tutulur.

Aktif bağlamı makinece çözümlemek için:

```bash
python tools/krcn.py context --format json
```

İncelenen eski komut sözleşmelerini herhangi bir işlem çalıştırmadan görmek için:

```bash
python tools/krcn.py catalog
```

## Foundation doğrulaması

Repository sahiplik, provider ve import politikalarını ek bağımlılık olmadan doğrulamak için:

```bash
python tools/verify_repository.py
```

Bir import adayını mevcut güvenlik politikasıyla taramak için:

```bash
python tools/verify_repository.py --source <source-directory>
```

Doğrulama aracı secret, makineye özel yol, hassas bağlantı bilgisi, engellenmiş dosya türü ve uzun tire bulgularında başarısız olur. Ağ erişimi kullanmaz.

## Kurucu ve mimari sahibi

**Mehmet KARACAN** - KRCN Core kurucusu ve özgün mimarinin sahibi
