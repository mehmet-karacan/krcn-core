# KRCN Core

**KRCN Core**, projeleri, belgeleri, iş taleplerini, kararları, kalıcı bağlamı ve belleği ortak bir çekirdek üzerinden birbirine bağlayan, yerel öncelikli (local-first) bir platformdur. Kullanıcı hedefini doğal dille anlatır; sistem bu hedefi somut bir göreve, kaynak ilişkisine ve doğrulanabilir bir plana dönüştürür - kullanıcı verisine asla sessizce dokunmadan.

KRCN Core'un temel yaklaşımı ve özgün mimarisi **Mehmet KARACAN** tarafından tasarlanmıştır. Bu repository, o mimari vizyonu sürdürülebilir ve açık bir teknik yapıya dönüştürmek için yürütülür.

## Neden KRCN Core

Çoğu araç ya ürünü kullanıcı verisiyle aynı yere gömer (güncelleme veri kaybı riski taşır) ya da kullanıcı verisini bir buluta taşır (yerel öncelik ve gizlilik kaybolur). KRCN Core bu ikisini birbirinden ayırır:

- **Çekirdek** (kod, şema, politika, migration) Git ile sürümlenir ve kontrollü şekilde güncellenir.
- **Kullanıcı verisi** (projeler, belgeler, talepler, kararlar, bellek) kullanıcının kendi makinesinde, `KRCN_HOME` altında kalır ve hiçbir güncelleme onu sessizce değiştiremez.
- **Dış kaynaklar** (proje dizinleri, veritabanları) yerinde okunur; KRCN içine kopyalanmaz.

Bu ayrım sayesinde çekirdek her güncellendiğinde kullanıcının projeleri, ayarları ve geçmişi bozulmadan kalır.

## Mimari genel görünüm

İstek yukarıdan aşağı ilerler: istemciler aynı application service sözleşmesini kullanır, KRCN Core policy ve onay sınırlarını uygular, sonuç yalnızca doğru sahiplik alanına yazılır. Proje kaynakları kendi dizinlerinde kalır; dış sağlayıcı ve veritabanı erişimleri ise adapter, policy ve açık kullanıcı onayı olmadan çalışmaz.

![KRCN Core mimari genel görünümü](docs/diagrams/krcn-core-architecture.svg)

Bu görünümde turuncu çerçeveli tek odak, Git ile sürümlenen KRCN Core'dur. Alt bölüm kullanıcıya ait yerel `KRCN_HOME` sınırını, kesikli dış düğümler ise KRCN tarafından sahiplenilmeyen kaynakları gösterir.

| Katman | Sorumluluk |
| --- | --- |
| **İstemci** | CLI, Codex, Claude Code, MCP sunucusu veya bir plugin. Doğal dili tipli bir isteğe çevirir; ürün kuralı tanımlamaz. |
| **KRCN Core / Application Service** | Tüm istemcilerin çağırdığı tek, transport-bağımsız servis katmanı; ürün kurallarının ve güvenlik sınırlarının kanonik sahibidir. |
| **Policy / Capability / Approval kapısı** | Her yan etkiyi dry-run ve exact-plan olarak görünür kılar, gerekiyorsa kullanıcı onayı ister; hiçbir istemci bu kapıyı atlayamaz. |
| **Project Capsule / Work Graph / Retrieval** | Proje bağlamını ve kullanıcı kararlarını korur, yetkili görev durumunu Work Graph'tan okur, bilgiyi exact, hibrit, semantik ve kaynak kod indekslerinden getirir. |
| **Agent Runtime / Orchestrator** | Görevi planlar, işi uygun worker'a yürütür, lease ve checkpoint durumunu korur, sonucu bağımsız bir verifier ile doğrular. |
| **Merge / Migration / Verify / Rollback** | Core güncellemelerini kullanıcı verisine dokunmadan uygular; başarısız doğrulamada geri alır. |

### Veri sahipliği haritası

| Alan | Konum | Temel kural |
| --- | --- | --- |
| Ürün çekirdeği | Git repository | Kod, şema, migration, policy tanımı ve teknik belgeler sürümlenir. |
| Kullanıcı verisi | `KRCN_HOME/projects/<project-id>` | Proje bağlamı, belgeler, talepler, defect kayıtları, görevler, kararlar, bellek ve kullanıcı policy'leri proje kapsülünde korunur. |
| Runtime ve derived state | `KRCN_HOME` | İş durumu korunur; türetilmiş içerik gerektiğinde yeniden üretilebilir. |
| Dış proje ve kaynaklar | Kendi fiziksel dizinleri | Yerinde okunur, KRCN içine kopyalanmaz, varsayılan olarak değiştirilmez. |
| Secret değerleri | Yerel veya harici secret store | Git'e, loglara veya backup içine yazılmaz. |

### Bir isteğin çalışma akışı

1. İstemci, doğal dil hedefini ortak bağlamla birlikte application service katmanına iletir.
2. Sistem ilgili proje, kaynak, policy, capability ve mevcut çalışma durumunu çözümler.
3. Yan etkiler `dry-run` ve exact plan olarak görünür hale getirilir.
4. Gereken kullanıcı onayından sonra işlem ortak servis üzerinden uygulanır.
5. Sonuç kanıtlarla doğrulanır; kullanıcı verisi ve dış kaynak sınırları korunur.

Core güncellemeleri de aynı disiplinle ilerler: incele, `dry-run` göster, yedekle, uygula, gerekiyorsa migration çalıştır, doğrula; doğrulama başarısız olursa otomatik rollback devreye girer. Tam sözleşme için `docs/specifications/UPDATE-MERGE-CONTRACT.md`.

## Doğal dille araştırma

Bir proje dizininde Codex, Claude Code veya OpenCode ile konuşurken uzun bir araştırma
promptu hazırlaman gerekmez. Örneğin şunları söyleyebilirsin:

```text
Bu hatanın kök nedenini araştır.
Bunu detaylı araştır.
Spring Boot ile Quarkus'u karşılaştır.
Bu yaklaşımı araştır ve planla.
```

İstemci aktif projeyi ve konuşmadaki konuyu KRCN Research Action'a taşır. `Bunu`
ifadesinin konusu konuşmada yoksa sistem konu uydurmaz, yalnız eksik konuyu sorar.
Araştırma sonucu uygulama gerektiriyorsa ayrıca doğrulanmış plan ve normal değişiklik
onayı gerekir.

Doğrudan terminal kullanımı için aynı doğal dil girişi şöyledir:

```bash
krcn ask "Bu projedeki rapor hatasını detaylı araştır"
```

## Geliştirme durumu

Faz 0 - Faz 21 tamamlandı. Proje kapsülü, KRCN home yerleşim v2, kesin Work Graph, fencing korumalı ajan kuyruğu, satır verisi toplamayan Oracle metadata RAG ve kanıt öncelikli birleşik retrieval hazırdır. Görev durumu, geçmişi ve teslim kanıtları ajan oturumundan veya vektör benzerliğinden değil proje kapsülündeki revizyonlu kayıtlardan okunur. Proje kaynaklarını kopyalamayan artımlı kaynak kod RAG indeksi aynı yerleşimde çalışır. Oracle package spec, body, şema yapısı ve bağımlılıkları kullanıcı politikaları korunarak ayrı sürümlenir. Faz 21 ile compaction dayanıklı devamlılık, kanonik execution trace ve status, taşınabilir proje kimliği, bağımsız verifier kimliği, generic DAG executor, Execution Coordinator, kapalı döngü model kararı, retrieval golden ölçümü ve açık application/CLI registry sınırları tamamlanmıştır. Yerel referans kaynaklarındaki kullanıcı verileri repository içine alınmamıştır. Faz detayları için `docs/plans/ROADMAP.md` ve `docs/progress/PHASE-21-COMPLETION.md`.

İlk proje entegrasyonu, yerel çalışma alanı, doctor ve hibrit bilgi araması için `docs/guides/HIZLI-BASLANGIC.md` belgesini kullanabilirsin.

## Başlarken

Windows, macOS veya Linux üzerinde doğrudan kurulum yapmak istersen repository içinde önce planı görüntüle, sonra onayladığın kurulumu uygula:

Windows:

```powershell
py tools\install_cli.py --plan-only
py tools\install_cli.py
```

macOS ve Linux:

```bash
python3 tools/install_cli.py --plan-only
python3 tools/install_cli.py
```

Uyumlu bir yapay zekâ istemcisinde ilk kez `Bu projeyi entegre et` dediğinde, CLI eksikse aynı plan ve onay akışını istemci yönetir. Kurulumdan sonra ilk isteği kaybetmeden proje entegrasyonuna devam eder. Kurulum, onaylı core clone'unu `KRCN_CORE_HOME` ile tanımlar ve `KRCN_HOME` kullanıcı veri konumunu değiştirmez. Core güncellemesinden sonra kurulum aracını yeniden çalıştır. Ayrıntılı sözleşme için `docs/specifications/CLI-INSTALLATION.md` belgesine bak.

```bash
python tools/krcn.py doctor
```

Bu komut kurulum gerektirmeden sağlık kontrolünü çalıştırır ve ortamın hazır olup olmadığını gösterir. Tüm komutlar, proje öğrenme, bilgi/bağlam/bellek servisleri, orchestrator ve release/rollback akışları dahil, `docs/specifications/CLI-REFERENCE.md` dosyasında toplanmıştır.

## Daha fazla bilgi

- Çalışma kuralları: `AGENTS.md`
- Araçtan bağımsız başlangıç bağlamı: `AI-CONTEXT.md`
- Komut referansı: `docs/specifications/CLI-REFERENCE.md`
- Yol haritası: `docs/plans/ROADMAP.md`
- Güncelleme sözleşmesi: `docs/specifications/UPDATE-MERGE-CONTRACT.md`
- Proje kapsülü sözleşmesi: `docs/specifications/PROJECT-CAPSULE-LAYOUT.md`

Codex doğrudan `AGENTS.md` kullanır; Claude Code için `CLAUDE.md` aynı ortak kaynakları içe aktarır; diğer istemciler ve plugin'ler `.ai/repository-context.json` manifestini okuyabilir.

## Kurucu ve mimari sahibi

**Mehmet KARACAN** - KRCN Core kurucusu ve özgün mimarinin sahibi
