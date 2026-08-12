# Plan 018 - Proje pilotu, model yeterliliği ve görev mirası

## Durum

Devam ediyor.

## İlerleme

- [x] 1. Proje yetkinlik profili
- [x] 2. Model envanteri ve sağlık kontrolü
- [x] 3. Proje özel mikro benchmark
- [ ] 4. Uzmanlık bazlı model puanlama ve atama
- [ ] 5. Delegated work unit sözleşmesi
- [ ] 6. Orchestrator ve kalıcı runtime köprüsü
- [ ] 7. Ana ajan coordinator politikası ve istemci adaptörleri
- [ ] 8. `gpu-fusion` pilotu ve kabul testleri
- [ ] 9. Altı gerçek proje entegrasyonu
- [ ] 10. Geçmiş ve aktif görev aktarımı

## Amaç

KRCN Core'u proje özel yetkinlik, model yeterliliği ve zorunlu alt ajan orkestrasyonu ile olgunlaştırmak, bu mimariyi `gpu-fusion` üzerinde doğrulamak, ardından altı gerçek projeyi kaynakları kopyalamadan entegre etmek ve yüksek güvenli görev mirasını ilgili proje kapsüllerine aktarmak.

## Mimari sıra

1. Proje yetkinlik profili
2. Model envanteri ve sağlık kontrolü
3. Proje özel mikro benchmark
4. Uzmanlık bazlı model puanlama ve atama
5. Delegated work unit sözleşmesi
6. Orchestrator ve kalıcı runtime köprüsü
7. Ana ajan coordinator politikası ve istemci adaptörleri
8. `gpu-fusion` pilotu ve kabul testleri
9. Altı gerçek proje entegrasyonu
10. Geçmiş ve aktif görev aktarımı

## Proje özel çalışma modeli

- Proje profili teknoloji, framework, mimari, veri tabanı, test, build, delivery ve kalite ihtiyaçlarını kanıtlarıyla çıkarır.
- Kullanıcının model envanteri global tutulur, fakat sağlık ve yeterlilik kararları proje ve iş türü kapsamında verilir.
- Model ataması `project_id + workload_profile + model_id + benchmark_digest` birleşik kimliğine bağlıdır.
- Kullanıcı model bildirmezse istemcinin varsayılan modeli kullanılır. Orkestrasyon ve uzmanlık ayrımı yine korunur.
- Trust role yetkiyi, workload profile uzmanlığı, model assignment ise yeterlilik kararını temsil eder. Bu üç katman birbirinin yerine geçmez.
- Kayıtlı proje üzerinde kanıt veya işlem gerektiren işlerde ana ajan coordinator olur. Kaynak inceleme, analiz, tasarım, geliştirme ve test alt ajan iş birimlerine ayrılır.
- İstemci gerçek alt ajan desteklemiyorsa sistem bunu gizlemez ve açık bir izole rol fallback'i kullanır.

## Güvenlik sınırları

- Proje kaynakları yerinde ve salt okunur bağlanır. KRCN home içine kopyalanmaz.
- Kullanıcı policy kararları, özellikle veri tabanı erişim sınırları, türetilmiş profille ezilmez.
- Token, parola, bağlantı değeri ve gerçek credential saklanmaz.
- Uzak modele gerçek proje içeriği göndermek ayrı provider onayı gerektirir.
- Model seçimi yetki vermez. Mutation, database, adapter ve provider kapıları bağımsız kalır.
- Kullanıcı verisi değişiklikleri exact-plan ve açık onay olmadan uygulanmaz.
- Eksik veya kısmi tarama sonucu model ataması için güvenilir sayılmaz.

## Pilot proje

İlk pilot `gpu-fusion` projesidir. Pilot sırasında yetkinlik profili, model sağlığı, proje özel benchmark, uzmanlık atamaları, paralel alt ajan çalışması, bağımsız verifier ve fallback davranışı doğrulanır.

## Hedef gerçek projeler

- `plsql-test-sync`
- `schema-compare-platform`
- `schema-transform-platform`
- `utplsql`
- `sky-microservis`
- `sky-ui`, keşfedilen güvenli proje kimliği `call-center-ui`

Fiziksel proje ve eski MK-Hub yolları makineye özel kullanıcı verisidir. Git'e yazılmaz. Çalışma sırasında kullanıcı tarafından sağlanan yerel binding kayıtlarıyla çözülür.

## Görev mirası

1. Eski MK-Hub kayıtlarını güvenilmeyen ve salt okunur kaynak olarak tara.
2. Geçmiş ve aktif görev adaylarını proje, durum, commit ve kanıt ilişkilerine göre sınıflandır.
3. Yalnız yüksek güvenli kayıtları otomatik adaylaştır.
4. Çakışan görev kimliklerini `project_id + task_id` ile ayır.
5. Belirsiz kayıtları başlık veya durum uydurmadan inceleme listesine al.
6. Onaylanan kayıtları provenance bilgisiyle Work Graph içine yerleştir.
7. Aktif görevler için resume, geçmiş görevler için arşiv görünümü oluştur.

## Kabul ölçütleri

- Proje yetkinlikleri kanıtlı, modül kapsamlı, secret içermeyen ve deterministik bir profile dönüşür.
- Aynı proje farklı iş türleri için farklı birincil ve yedek model kullanabilir.
- Sağlıksız veya benchmark eşiğini geçemeyen model alt ajana atanmaz.
- Geliştirme ve bağımsız doğrulama mümkün olduğunda farklı model veya model ailesiyle yürür.
- Ana ajan proje işinde coordinator sınırına uyar ve gerçek delegasyon yoksa bunu açıkça bildirir.
- `gpu-fusion` pilotu uçtan uca kabul testinden geçer.
- Altı kaynak proje birbirinden bağımsız kapsüllerde çalışır.
- Proje kaynak dosyaları KRCN home içine kopyalanmaz.
- Eski görev kaydı kanıtsız biçimde aktif göreve dönüştürülmez.
- Her aktarılan görev kaynak kaydı, proje ilişkisi ve güven seviyesi taşır.
- `nerede kaldık` sorusu her proje için doğru aktif görev bağlamını verir.
