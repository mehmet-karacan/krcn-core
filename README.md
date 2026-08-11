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
6. Doğrulama başarısız olursa doğrulanmış backup üzerinden otomatik rollback uygulanır.

## Güncel geliştirme durumu

Faz 1, Faz 2, Faz 3 ve Faz 4 tamamlandı. Revision-aware bilgi kataloğu, retrieval, bütçeli context paketleri, onay kontrollü Memory Gate ve ortak istemci servisleri hazırdır. Faz 5 orchestrator ve doğal dil görev akışı geliştirmesi aktif olarak yürütülmektedir. Yerel referans kaynaklarındaki kullanıcı verileri içeri alınmamıştır.

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

Kayıtlı projeleri ortak ve istemciden bağımsız servis sözleşmesi üzerinden yönetmek için:

```bash
python tools/krcn.py project list
python tools/krcn.py project inspect <project-id>
python tools/krcn.py project onboard --workspace-id <workspace-id> --project-id <project-id> --binding-id <binding-id> --name <project-name> --source <source-directory>
python tools/krcn.py project rescan <project-id>
```

Onboarding ve rescan komutları varsayılan olarak yalnızca plan üretir. Uygulama için önceki dry-run sonucundaki plan kimliği ve user-data değişikliği varsa açık onay kimliği gerekir. CLI, SDK, MCP, plugin ve yapay zekâ istemcileri aynı servis katmanını kullanır.

Revision-aware bilgi kataloğunu ve Faz 4 ortak servislerini kullanmak için:

```bash
python tools/krcn.py knowledge catalog
python tools/krcn.py knowledge exact --request-file <application-arguments.json>
python tools/krcn.py knowledge dependencies --request-file <application-arguments.json>
python tools/krcn.py knowledge semantic --request-file <application-arguments.json>
python tools/krcn.py context-package build --request-file <application-arguments.json>
python tools/krcn.py memory propose --request-file <application-arguments.json>
python tools/krcn.py memory review --request-file <application-arguments.json>
python tools/krcn.py memory persist --request-file <application-arguments.json>
```

Bu komutlar ürün kuralı tanımlamaz; doğrudan ortak application service sözleşmesini çağırır. Uzak semantic arama için exact oturum onayı ve istemci tarafından açıkça bağlanmış bir scorer gerekir. Memory persist varsayılan olarak yalnızca plan üretir; kalıcı yazım aynı plan kimliği ve review ile eşleşen kullanıcı onayı olmadan çalışmaz.

Yerel bir kurulumu incelemek, trusted release farkını görmek ve exact plan üretmek için:

```bash
python tools/krcn.py installation inspect --installation <installation-directory>
python tools/krcn.py installation verify --installation <installation-directory>
python tools/krcn.py release diff --installation <installation-directory> --release <release-directory> --trusted-manifest-sha256 <sha256>
python tools/krcn.py release merge --installation <installation-directory> --release <release-directory> --trusted-manifest-sha256 <sha256>
```

`release merge` varsayılan olarak yalnızca plan üretir. Apply için aynı komut `--apply --expected-plan <plan-id>` seçenekleriyle yeniden çalıştırılır. Plan user-data migration veya delete içeriyorsa `--approval-id <approval-id>` de gerekir. Tamamlanmış veya kesintiye uğramış bir deployment için rollback de önce planlanır, sonra exact plan ve gerekli onayla uygulanır:

```bash
python tools/krcn.py deployment rollback <deployment-id> --installation <installation-directory>
```

Repository paketini ağ kullanmadan mevcut Python ortamına kurmak ve sağlık kontrolünü çalıştırmak için:

```bash
python -m pip install --no-index --no-deps --no-build-isolation .
krcn doctor
```

Kurulum yapmadan aynı sağlık kontrolünü çalıştırmak için:

```bash
python tools/krcn.py doctor
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
