# Plan 021 - Mimari devamlılık ve taşınabilirlik

## Amaç

Mevcut KRCN Core bileşenlerini yeni bir platform eklemeden tek yürütme kimliği, tek plan, tek status ve tek trace altında birleştirmek; model, istemci, oturum ve cihaz değişiminde çalışma durumunun kanıta bağlı biçimde yaşamasını sağlamak.

Bu faz yeni bir temel mimari kurmaz. Çalışan güvenlik ve kalıcılık omurgasını korur, eksik olan bileşim, devamlılık, taşınabilirlik ve ölçüm katmanlarını tamamlar.

## Kapsam dışı

- PostgreSQL, Redis, harici vector veya graph veritabanı benimseme
- Mikroservis, Kubernetes veya harici durable workflow engine
- Ownership, exact-plan, provider disclosure ve verifier sözleşmelerinin gevşetilmesi
- Kullanıcı verisi, `.krcn` içeriği veya dış proje kaynağı üzerinde onaysız migration

## Baseline

- Kaynak branch: `main`
- Baseline commit: `2e4d23a`
- Çalışma branch'i: `mimari-devamlilik-ve-tasinabilirlik`
- Ayrı çalışma kopyası kullanılır; `main` üzerinde doğrudan geliştirme commit'i yapılmaz.

## İş paketleri

Sıra, P0 önceliğini korurken paylaşılan büyük dosyalara dokunan paketleri geriye alır.

1. **Zemin ve devir baseline'ı.** Faz kaydı, plan, ilerleme kataloğu ve aktif pointer sınırı. Ürün davranışı değişmez.
2. **Güncel HEAD yayınlanabilirlik kanıtı.** Zorunlu CI tetikleyicisi, baseline kayıtlarına kaynak commit bağlama, release attestation alanları.
3. **V1 değişmez mimari sözleşmeleri.** Ownership, exact-plan, provider gate, Work Graph, verifier ve queue invariant'larının ADR ile dondurulması.
4. **Compaction dayanıklı devamlılık.** Sınırlı `ContinuitySnapshot`, append-only `WorkJournal` ve yetki taşımayan `HandoffRecord`.
5. **Kanonik izleme ve durum.** `ExecutionTrace` ve tek `StatusProjection`.
6. **Taşınabilir proje kimliği.** Relocation sınıflandırması ve exact rebind kararlarının sertleştirilmesi.
7. **Model yetenek koruma kapısı.** Hard güvenlik ile soft yöntem ayrımı ve golden karşılaştırma.
8. **Bağımsız verifier kimliği.** Generic akışta ayrı execution identity zorunluluğu.
9. **Generic DAG executor.** Research runtime'daki scheduler mekanizmasının yeniden kullanılabilir hale getirilmesi.
10. **İş katalog projection'ı.** Work Graph'tan üretilen `WORK-INDEX.md`.
11. **Kuyruk altyapısı uygunluk ölçümü.** SQLite baseline'ına karşı aday karşılaştırması ve ADR.
12. **Execution Coordinator.** Mevcut servisleri tek uçtan uca akışta compose eden modül.
13. **Model karar servisi.** Routing, health, benchmark ve maliyetin kapalı döngüye bağlanması.
14. **Retrieval golden set.** Gerçek soru kümesi ve ölçek fixture'ları.
15. **Application ve CLI iç bölünmesi.** Tek sözleşme korunarak domain ve komut modüllerine ayrılma.

## Kabul ölçütleri

- Her paket tek bir doğrulanabilir davranış veya karar sınırını kapatır.
- Güncel HEAD için zorunlu kontrol sonucu görünür ve baseline kayıtları kaynak commit'e bağlıdır.
- Devamlılık snapshot'ı sert boyut sınırını aşmaz ve authoritative kayıtlarla çelişince reddedilir.
- Ani süreç sonlanmasında son doğrulanmış adım yeni oturumda bulunur.
- Aynı kaynak revizyonunun farklı dizine taşınması yalnız locator düzeltmesi üretir; içerik farkı sessizce kabul edilmez.
- Verifier, doğruladığı worker'lardan farklı execution identity taşır.
- Bağımsız iş birimleri gerçek zamanda çakışarak çalışır ve her adım sonunda checkpoint bırakır.
- Kullanıcı tek kanonik durum görür; ham domain durumları doğrudan yansıtılmaz.
- Devamlılık, trace ve katalog kayıtları execution authority üretmez.
- Kullanıcı verisi, `.krcn` içeriği ve dış proje kaynakları değiştirilmez.

## Riskler

- Coordinator bütün kuralları yeniden uygularsa merkezi bir god service oluşur. Yalnız compose etmelidir.
- Generic executor aşırı soyutlanırsa karmaşıklık artar. İlk kapsam mevcut plan adımı, kuyruk ve handler sözleşmeleridir.
- Paylaşılan `application.py` ve `cli/app.py` dosyaları paralel çalışmayla çakışabilir. Bu nedenle iç bölünme son pakete alınmıştır.
- Snapshot source of truth'a dönüşürse yeni bir durum kopyası oluşur. Snapshot yalnız projection kalmalıdır.

## Referanslar

- İlerleme kayıtları kataloğu: `docs/progress/PROGRESS-KATALOGU.md`
- Faz başlangıç kaydı: `docs/progress/PHASE-21-KICKOFF.md`
