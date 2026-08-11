# KRCN Core geliştirme yol haritası

## Ana hedef

KRCN Core, Git ile dağıtılan ürün çekirdeğini yerel proje ve kullanıcı verisinden ayıracak. Kullanıcı yeni sürümü çektiğinde mevcut projeler, belgeler, talepler, görevler, ayarlar ve entegrasyonlar bozulmadan çalışmaya devam edecek.

Yerel dosyalar varsayılan olarak Git'e veya başka bir uzak servise gönderilmeyecek. Git repository yalnızca core kodunu, sürümlenebilir şemaları, politikaları, migration tanımlarını, şablonları ve teknik belgeleri taşıyacak.

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

- CI testleri, baseline regresyonları ve migration testleri ekle.
- Windows ve macOS kurulum senaryolarını doğrula.
- Release oluşturma, paketleme, doctor ve rollback akışını tamamla.
- Temiz kurulum ve mevcut kurulum güncelleme testlerini otomatikleştir.
- Başka bir AI veya geliştirici için devir ve geliştirme bağlamını doğrula.

Tamamlanma ölçütü: `clone -> install -> init/onboard -> doctor -> run` ve `pull -> merge into -> verify` akışları belgelenmiş ve test edilmiş olmalı.

## Değişmez kabul ölçütleri

- Yerel kullanıcı verisi açık talimat olmadan uzak sisteme gönderilmez.
- Core güncellemesi kullanıcı verisini silmez veya sessizce değiştirmez.
- Her mutasyon öncesinde etki alanı görülebilir.
- Her uygulama geri alınabilir veya yeniden üretilebilir olmalıdır.
- Tüm kritik sonuçlar test, hash, schema veya kaynak referansıyla doğrulanır.
- AI ve CLI çalışma sözleşmeleri İngilizce olabilir; insan operasyon kayıtları doğal Türkçeyle yazılır.
- Uzun tire karakterleri kullanılmaz.
