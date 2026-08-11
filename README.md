# KRCN Core

KRCN Core; projeleri, belgeleri, işleri/talepleri, kararları, kalıcı bağlamı ve belleği ortak bir çekirdeğe bağlayan yerel öncelikli platformdur.

KRCN Core'un temel yaklaşımı ve özgün mimarisi Mehmet KARACAN tarafından oluşturulmuştur. Proje, bu mimari vizyonun sürdürülebilir ve geliştirilebilir bir açık teknik yapıya dönüştürülmesi amacıyla yürütülmektedir.

## Temel hedef

Kullanıcı bir CLI veya yapay zekâya doğal dille hedefini söyler. Sistem gerekli görev tanımını, kaynak ilişkilerini, bağlamı, güvenlik sınırlarını ve doğrulama adımlarını üretir. Bunu yaparken mevcut kullanıcı verisini korur ve yalnız kontrollü core güncellemeleri uygular.

## Güncelleme ilkesi

Git'ten gelen yeni core sürümü:

1. mevcut kurulumu ve veri sahipliğini inceler,
2. değişiklikleri dry-run olarak gösterir,
3. kullanıcı verisini ve yerel secretları korur,
4. gerekiyorsa şema migration'ı ve türetilmiş indeks rebuild'i planlar,
5. yedekleme ve uyumluluk kontrollerinden sonra uygular,
6. doğrulama başarısızsa güvenli rollback sunar.

## İlk aşama

Repository şu anda foundation/baseline hazırlığındadır. Yerel referans kaynakları henüz içeri alınmamıştır. Aktarım öncesinde core/runtime/user-data/derived/secrets ayrımı çıkarılacaktır.

Kök çalışma kuralları için `AGENTS.md` dosyasını okuyun.

Gelistirme sirasi icin `docs/plans/ROADMAP.md`, guncelleme guvenlik sozlesmesi icin `docs/specifications/UPDATE-MERGE-CONTRACT.md` kullanilir.

## Kurucu ve mimari sahibi

**Mehmet KARACAN** - KRCN Core kurucusu ve özgün mimarinin sahibi
