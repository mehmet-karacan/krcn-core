# Faz 8 tamamlandı

## Sonuç

Proje bazlı KRCN kullanıcı evi ve üretim olgunlaştırma fazı tamamlandı. Bir proje ilk kullanımda varsayılan olarak kendi kökündeki `.krcn` alanını öneriyor; kullanıcı isterse özel bir yerel konum seçebiliyor veya işlemi iptal edebiliyor. Aynı proje sonraki kullanımda kayıtlı konumu yeniden sormadan çözümleyebiliyor.

## Tamamlanan on adım

1. Araştırma bulguları mevcut repository üzerinde doğrulandı ve güvenli kapsama uyarlandı.
2. Varsayılan, özel ve açık mevcut kullanıcı evi çözümleme sözleşmesi oluşturuldu.
3. Exact plan, Git koruması ve doğrulama kullanan proje evi initialization tamamlandı.
4. Proje öğrenme, CLI, SDK, MCP, plugin, Codex ve Claude istemcileri aynı konum seçimine bağlandı.
5. Backup destekli migration ve temiz clone restore akışları tamamlandı.
6. Deployment durumu, eş zamanlı kayıt yazma, memory staleness ve yarım migration açıkları kapatıldı.
7. Skill, adapter, secret provider, worker ve verifier çalışma kayıtları ortak capability sınırına alındı.
8. Salt okunur gerçek SQLite entegrasyonu ile FTS5 ve deterministik vektör kullanan hibrit RAG tamamlandı.
9. Linux CI, yüzde 60 coverage kapısı, runtime doctor, olay zaman çizelgesi, güvenli hata yönlendirmesi ve hızlı başlangıç eklendi.
10. Proje konumu, Git, no-copy, taşınabilirlik, policy, secret, entegrasyon, retrieval, istemci eşitliği ve temiz kurulum kabul matrisi birlikte doğrulandı.

## Korunan değişmezler

- `.krcn` ve diğer yerel kullanıcı verileri Git'e eklenmiyor.
- Harici proje, belge ve veritabanı dosyaları yerinde kalıyor; KRCN içine kopyalanmıyor veya değiştirilmiyor.
- Kullanıcının policy kayıtları migration ve restore boyunca byte düzeyinde korunuyor.
- Yalnız `SELECT` izni verilen veritabanı entegrasyonu mutasyon çalıştıramıyor.
- Secret değerleri repository, public yanıt, log, indeks veya taşınabilir backup içine girmiyor.
- Yeni bir istemci, plugin veya yapay zekâ aynı application service, capability, policy, mutation ve provider kapılarını kullanıyor.
- Uzak provider kullanımı varsayılan değil ve ayrı oturum onayı olmadan etkinleşmiyor.
- Derived indeks bozulursa veya katalog değişirse arama kapalı biçimde rebuild istiyor.

## Kalite kanıtı

- Tam hermetik test paketi geçti.
- Faz 8 kabul matrisi geçti.
- Repository context ve güvenlik taraması temiz geçti.
- Doctor, SQLite FTS5, coverage baseline ve Faz 0-8 baseline kontrolleri geçti.
- Tam pakette 466 test geçti, 2 ortam bağımlı test atlandı.
- Python monitoring satır coverage değeri yüzde `64.01` oldu ve yüzde `60` CI eşiğini geçti.
- Yerel hibrit retrieval değerlendirmesi recall@5 ve MRR için `1.0` üretti.
- 1001 girdili referans katalog sorgu p95 değeri `161.665 ms` olarak ölçüldü.

## Kullanım ve bakım durumu

İlk kullanım yolu `docs/guides/HIZLI-BASLANGIC.md` belgesinde bulunuyor. Repository'ye giren herhangi bir uyumlu CLI, plugin veya yapay zekâ `AGENTS.md`, `AI-CONTEXT.md` ve `.ai/repository-context.json` üzerinden aynı bağlama ulaşabilir.

Faz 8 baseline `ready` durumundadır. Yeni bir faz, dış provider, yeni mutasyon yetkisi veya mimari kapsam genişlemesi Mehmet KARACAN'ın ayrı ve açık onayını gerektirir.
