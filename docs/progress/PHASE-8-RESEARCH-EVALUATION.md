# Faz 8 araştırma değerlendirmesi

## Amaç

Kullanıcı tarafından sağlanan mimari olgunlaştırma araştırmasının güncel KRCN Core repository'siyle karşılaştırılarak Faz 8 kapsamına alınacak doğrulanmış başlıkları kaydetmek.

Araştırma dosyaları repository'ye kopyalanmadı. Bulgular `2ab1cb1` baseline kodu, 404 test, repository doğrulaması ve doctor sonucu üzerinden yeniden kontrol edildi.

## Doğrulanan öncelikler

1. Deployment durum kontrolünde geçersiz `backing-up` değeri bulunuyor ve gerçek `failed` durumu yarım kalmış işlem algısına dahil edilmiyor.
2. Yerel kayıt yazımı atomik dosya değişimi kullanıyor ancak prosesler arası kritik bölge kilidi bulunmuyor.
3. Memory kayıtlarının context girişine eklenmesi kaynak revizyonuna bağlı staleness kontrolünü atlayabiliyor.
4. Orchestrator handler sözleşmeleri güçlü olsa da varsayılan worker ve verifier registry'leri gerçek handler içermiyor.
5. Secret reference doğrulaması bulunuyor ancak gerçek secret provider ve saklama adapter'ı yok.
6. Yerel semantic retrieval embedding değil, deterministik sözcük kesişim skoru kullanıyor ve ölçülmüş bir retrieval kalite seti bulunmuyor.
7. Proje rescan işlemi elle başlatılıyor; freshness kontrolü ve ölçek ölçümü sınırlı.
8. Linux CI, coverage ölçümü, runtime doctor kontrolleri ve insan tarafından okunabilir orchestration geçmişi eksik.

## Düzeltilen yorumlar

- Secret taraması tamamen eksik değildir. Information record ve portable backup akışlarında içerik taraması vardır. Faz 8 hedefi bunu ortaklaştırmak ve gerçek secret provider sınırı eklemektir.
- Proje discovery limitini aşınca eksik sonucu başarılı tam sonuç gibi kalıcılaştırmak güvenli değildir. Kısmi sonuç eklenirse açıkça eksik işaretlenmeli ve kullanıcıya gösterilmelidir.
- Worker ve verifier boşluğu core içine örtük yetkili handler eklenerek kapatılmayacaktır. Kayıt işlemi açık, capability-bound ve policy kontrollü kalacaktır.
- Zaman damgası veya indeks değişiklikleri deterministik digest ve migration sözleşmesini korumadan eklenmeyecektir.

## Uygulama kararı

Araştırma Faz 8 için girdi olarak kabul edildi. Öneriler doğrudan kopyalanmayacak; her bulgu mevcut güvenlik sınırlarına uyarlanacak, testle kanıtlanacak ve ayrı commit sonrasında tamamlanmış sayılacaktır.
