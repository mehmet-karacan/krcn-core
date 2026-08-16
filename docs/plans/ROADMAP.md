# KRCN Core geliştirme yol haritası

## Ana hedef

KRCN Core, Git ile dağıtılan ürün çekirdeğini yerel proje ve kullanıcı verisinden ayıracak. Kullanıcı yeni sürümü çektiğinde mevcut projeler, belgeler, talepler, görevler, ayarlar ve entegrasyonlar bozulmadan çalışmaya devam edecek.

Yerel dosyalar varsayılan olarak Git'e veya başka bir uzak servise gönderilmeyecek. Git repository yalnızca core kodunu, sürümlenebilir şemaları, politikaları, migration tanımlarını, şablonları ve teknik belgeleri taşıyacak.

## Durum özeti

- Faz 0 tamamlandı.
- Faz 1 tamamlandı.
- Faz 2 tamamlandı.
- Faz 3 tamamlandı.
- Faz 4 tamamlandı.
- Faz 5 tamamlandı.
- Faz 6 tamamlandı.
- Faz 7 tamamlandı.
- Faz 8 tamamlandı. Proje bazlı KRCN_HOME ve üretim olgunlaştırma baseline'ı hazır.
- Faz 9 tamamlandı. Sürekli ve eksik aşama onaran proje entegrasyonu hazır.
- Faz 10 tamamlandı. İçeriksiz ve artımlı kaynak kod RAG indeksi hazır.
- Faz 11 tamamlandı. Proje kapsülü ve yerleşim v2 hazır.
- Faz 12 tamamlandı. Work Graph ve görev ilişkileri hazır.
- Faz 13 tamamlandı. Ajan kuyruğu ve çalışma zamanı hazır.
- Faz 14 tamamlandı. Satır verisi toplamayan Oracle metadata RAG hazır.
- Faz 15 tamamlandı. Kanıt öncelikli birleşik RAG ve proje kapsamlı retrieval hazır.
- Faz 16 bekliyor. Gerçek projeler ve görev mirası entegre edilecek.
- Faz 17 - 22 tamamlandı. Model sağlığı, gerçek proje ve araştırma akışları,
  kalıcı görev ilerlemesi, iş belgesi yerleşimi, mimari devamlılık ve ölçümlü
  öğrenme yönetişimi hazır.
- Faz 23 aktif. Adaptive Routing mevcut yürütmeyi değiştirmeden shadow mode
  karar ve karşılaştırma kanıtı üretecek.

## Temel kullanım modeli

Kullanıcı bir CLI'a veya yapay zekâya hedefini doğal dille anlatabilecek. Sistem aşağıdaki adımları izleyecek:

1. Hedefi ve kabul ölçütlerini belirleyecek.
2. İlgili proje, belge, talep ve entegrasyonları bulacak.
3. Gerekli görev planını üretecek.
4. Veri sahipliği ve yetki sınırlarını kontrol edecek.
5. İşlemi uygulayacak.
6. Sonucu doğrulayıp Türkçe raporlayacak.

## Faz 0 - Mevcut durumu dondur ve tanımla

- Mevcut canlı sistem ile baseline adayını karşılaştır.
- Çalışan komutları, testleri, şemaları ve dizin yapısını kaydet.
- Canlı veriyi core, runtime, user-data, derived ve secrets olarak sınıflandır.
- Secret, kişisel veri ve kuruma özel bilgi taraması yap.
- Aktarılacak ve aktarılmayacak dosyalar için kullanıcı onayı al.

Tamamlanma ölçütü: Çalışan mevcut davranış ve veri sınırları, yeniden üretilebilir bir baseline raporuyla kayıt altına alınmış olmalı.

## Faz 1 - Repository ve sahiplik temeli

- Ürün kaynak kodunu KRCN Core repository yapısına yerleştir.
- `ownership-manifest.json` oluştur.
- Core, runtime, user-data, derived ve secrets yollarını makinece tanımla.
- Yerel veri dizinlerini `.gitignore` ve doğrulama kurallarıyla koru.
- Kurulum, test ve doctor komutlarının temelini hazırla.

Tamamlanma ölçütü: Repository temiz bir bilgisayarda kurulabilmeli ve hiçbir canlı veri Git'e eklenmemeli.

## Faz 2 - Yerel çalışma alanı ve entegrasyon modeli

- Proje kimliği ile fiziksel proje yolunu ayır.
- Proje, belge, talep, görev ve entegrasyon kayıt şemalarını tanımla.
- Kaynak projeleri varsayılan olarak salt okunur bağla.
- Her entegrasyon için adapter ve capability sözleşmesi oluştur.
- Yerel secret store ve ortam bazlı ayarları tanımla.

Tamamlanma ölçütü: Bir proje veya belge kaynağı kopyalanmadan KRCN Core'a tanıtılabilmeli.

## Faz 3 - Güvenli `merge into` güncelleme motoru

- `inspect`, `diff`, `merge into`, `verify` ve `rollback` akışını uygula.
- Her sürüm için release manifesti ve uyumluluk aralığı tanımla.
- Uygulama öncesinde `dry-run`, yedekleme ve conflict raporu üret.
- Yalnızca core tarafından yönetilen dosyaları güncelle.
- Yerel değişiklikleri ve kullanıcıya ait dosyaları koru.
- Şema migration'larını sürümlü ve tekrar çalıştırılabilir yap.
- Derived veriyi gerektiğinde migrate et veya yeniden oluştur.
- Başarısız doğrulamada otomatik geri dönüş sağla.

Tamamlanma ölçütü: Yeni core sürümü mevcut bir kuruluma uygulandığında projeler, belgeler, talepler ve entegrasyonlar veri kaybı olmadan çalışmaya devam etmeli.

## Faz 4 - Context, knowledge ve memory

- Authoritative source, knowledge, memory, state, history ve derived data ayrımını uygula.
- Revision-aware kaynak ve indeks modelini kur.
- Exact, semantic ve dependency tabanlı retrieval katmanlarını oluştur.
- Token bütçesi, kanıt ve kaynak referansları taşıyan context paketleri üret.
- Memory Gate ile yalnızca uygun ve doğrulanmış bilgiyi kalıcılaştır.

Tamamlanma ölçütü: Ajanlar aynı proje bağlamını model veya oturum değişse bile güvenilir biçimde kullanabilmeli.

## Faz 5 - Orchestrator ve doğal dil görev akışı

- İsteği hedef, plan, capability ve kabul ölçütlerine dönüştür.
- Planner, worker ve verifier sorumluluklarını ayır.
- Ajan, skill, tool ve model registry yapılarını uygula.
- Sonuçları kanıt ve doğrulama bilgisiyle kaydet.
- Kritik veya kapsam değiştiren kararlarda kullanıcı onayı iste.

Tamamlanma ölçütü: Kullanıcı yalnızca hedefini söylediğinde sistem güvenli bir uygulama planı oluşturup görevi sonuca götürebilmeli.

## Faz 6 - Release, kalite ve taşınabilirlik

- Kullanıcıya ait KRCN kayıtlarını repository dışında tek bir taşınabilir kullanıcı evinde topla.
- Dış proje dizinlerini kopyalamadan salt okunur binding ile tanı ve yol değişiminde doğrulanmış rebind uygula.
- Secret değerlerini ve dış proje içeriklerini dışlayan backup ile kontrollü restore akışını oluştur.
- Repo içindeki eski `.krcn` verisi için ayrı, yedekli ve geri alınabilir migration üret.
- CI testleri, baseline regresyonları ve migration testleri ekle.
- Windows ve macOS kurulum senaryolarını doğrula.
- Release oluşturma, paketleme, doctor ve rollback akışını tamamla.
- Temiz kurulum ve mevcut kurulum güncelleme testlerini otomatikleştir.
- Başka bir AI veya geliştirici için devir ve geliştirme bağlamını doğrula.

Tamamlanma ölçütü: `clone -> install -> init/onboard -> doctor -> run` ve `pull -> merge into -> verify` akışları belgelenmiş ve test edilmiş olmalı.

## Faz 7 - Doğal dille proje öğrenme ve aktivasyon

- "Öğren", "tanı", "tanıt", "entegre et", `learn`, `register` ve `onboard` niyetlerini ortak core içinde çözümle.
- Yalnız proje dizininden görünen ad, workspace, project ve binding kimliklerini türet.
- Onboarding ile ilk read-only discovery sonucunu tek exact planda birleştir.
- `project.learn` operation değerini CLI, SDK, MCP, plugin, Codex ve Claude için ortaklaştır.
- Proje dizininde dosya kopyalamadan veya KRCN dosyası oluşturmadan çalış.

Tamamlanma ölçütü: Kullanıcı yalnız mevcut proje dizinini verdiğinde sistem güvenli inference yapıp exact planı sunmalı ve tek onaydan sonra projeyi KRCN'e tanıtıp ilk discovery kaydını tamamlamalı.

## Faz 8 - Proje bazlı KRCN_HOME ve mimari olgunlaştırma

- Proje kapsamındaki varsayılan kullanıcı evini `<proje-kökü>/.krcn` olarak öner.
- İlk kullanımda konumu, Git dışlama sınırını ve backup gereksinimini kullanıcıya göster.
- Varsayılan konum, özel konum ve iptal kararlarını aynı exact-plan akışında ele al.
- Mevcut merkezi kullanıcı evleriyle geriye dönük uyumluluğu ve kontrollü migration'ı koru.
- Eş zamanlı yazma, deployment durumu, staleness ve kurtarma açıklarını kapat.
- Gerçek adapter, worker, verifier ve secret provider genişleme sınırlarını tamamla.
- Retrieval kalitesi, ölçek, CI, gözlemlenebilirlik ve kullanıcı deneyimini ölçülebilir hale getir.

Tamamlanma ölçütü: Proje bazlı veya özel konumda çalışan KRCN verisi Git'e ve proje kaynaklarına karışmadan kurulabilmeli, taşınabilmeli, eş zamanlı kullanıma dayanmalı ve farklı istemcilerden aynı güvenlik sözleşmesiyle işletilebilmelidir.

## Faz 9 - Sürekli proje entegrasyonu

- `entegre et` niyetini `project.integrate` yaşam döngüsüne yönlendir.
- Yeni veya kayıtlı projelerde eksik kayıt, keşif, bilgi, capability, vektör indeks ve doğrulama aşamalarını tamamla.
- Manuel ve otomatik tarama kiplerini sonuçlarda açıkça göster.
- Otomatik taramayı varsayılan 24 saatlik güncellik policy'sine bağla.
- Güncel ve tam entegrasyonu no-op olarak sonuçlandır.
- Teknolojiye uygun rol ve skill profilini merkezi capability registry'den seç.
- Kaynak değiştiğinde bilgi kayıtlarını ve yeniden üretilebilir hibrit indeksi güncelle.

Tamamlanma ölçütü: Kullanıcı yalnız proje dizinini verip `entegre et` dediğinde sistem bütün entegrasyon aşamalarını tek exact planda hazırlamalı; kayıtlı projelerde eksikleri onarmalı ve normal proje çalışması öncesinde güncelliği otomatik denetleyebilmelidir.

## Faz 10 - Kaynak kod RAG indeksi

- Desteklenen kaynak ve yapılandırma dosyalarını salt okunur binding üzerinden seç.
- Dosyaları göreli yol ve kesin satır aralığı taşıyan parçalara ayır.
- Ham kaynak metni veya fiziksel proje yolunu saklamadan vektör ve güvenli sembol metadatası üret.
- Değişmeyen dosya parçalarını yeniden kullan, değişenleri güncelle ve silinenleri çıkar.
- Her proje için ayrı, atomik ve yeniden üretilebilir SQLite indeks oluştur.
- Arama sonuçlarını gerçek proje dosyasından hash doğrulamalı ve anlık olarak oku.
- Kaynak kod indeksini `project.integrate`, resume, CLI ve istemci başlangıç bağlamına bağla.
- Uzak embedding kullanımını ayrı provider planı ve session onayının arkasında tut.

Tamamlanma ölçütü: `entegre et` isteği tam kaynak kod indeksini de hazırlamalı; arama sınıf, metot, sembol ve kod parçası seviyesinde göreli yol ve satır kanıtı döndürmeli; proje kaynakları KRCN alanına kopyalanmamalı ve artımlı güncelleme gerçek projede doğrulanmalıdır.

## Değişmez kabul ölçütleri

- Yerel kullanıcı verisi açık talimat olmadan uzak sisteme gönderilmez.
- Core güncellemesi kullanıcı verisini silmez veya sessizce değiştirmez.
- Her mutasyon öncesinde etki alanı görülebilir.
- Her uygulama geri alınabilir veya yeniden üretilebilir olmalıdır.
- Tüm kritik sonuçlar test, hash, schema veya kaynak referansıyla doğrulanır.
- AI ve CLI çalışma sözleşmeleri İngilizce olabilir; insan operasyon kayıtları doğal Türkçeyle yazılır.
- Uzun tire karakterleri kullanılmaz.
