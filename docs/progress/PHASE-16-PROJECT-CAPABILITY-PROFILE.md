# Faz 16 proje yetkinlik profili

## Durum

Tamamlandı.

## Sonuç

Proje entegrasyonu artık yalnız teknolojiye göre rol ve skill seçmiyor. Kaynağı kopyalamadan, proje ve modül bazlı semantik yetkinlik profili oluşturuyor.

Profil şu boyutları kapsıyor:

- Teknolojiler
- Frameworkler
- Mimari
- Veri tabanları
- Test
- Build
- Delivery
- Kalite
- Uzman alt ajan iş yükleri

## Güvenlik

- Yalnız discovery kaydındaki dosyalar okunuyor.
- Dosya boyutu ve SHA-256 özeti yeniden doğrulanıyor.
- Sembolik bağlantı ve kaynak kökü dışına çıkış reddediliyor.
- Hassas içerik bulunan dosyadan hiçbir yetkinlik veya kanıt çıkarılmıyor.
- Kaynak metni, fiziksel yol ve hassas değer profile yazılmıyor.
- Profiler ağ erişimi veya proje kodu çalıştırmıyor.
- Profil model seçmiyor ve yetki vermiyor.
- Token içeren manifest, pipeline, container ve SQL dosyaları path kanıtı da üretmiyor.
- Normal geliştirici iletişim alanları güvenli dependency analizini engellemiyor.
- Dosya, toplam bayt ve evidence bütçeleri büyük proje taramasını sınırlıyor.
- Bozuk manifestler entegrasyonu durdurmak yerine limitation olarak kaydediliyor.
- Plan ve uygulama arasında profiler policy değişirse herhangi bir kayıt yazılmadan plan reddediliyor.
- Eksik tarama `partial-safe` olarak işaretleniyor ve model ataması için güvenilir kabul edilmiyor.
- Test bağımlılıkları üretim frameworkü veya backend yetkinliği oluşturmuyor.
- Dokümantasyon ve örnek dizinlerindeki marker dosyaları üretim yetkinliği oluşturmuyor.

## Geriye uyumluluk

Yeni ayrı bir user-data koleksiyonu açılmadı. Yapılandırılmış profil mevcut `<project-id>-capabilities` knowledge kaydına eklendi. Böylece exact-plan, onay, revision, RAG, kapsül ve taşınabilirlik davranışı korundu.

Eski yüzeysel profil geçersiz sayılarak mevcut `capability-profile` aşamasında bir kez onaylı onarım planına giriyor. Güncel profil sonraki otomatik kontrolde no-op kalıyor. Standart `.git` dışlamaları tekrar tarama döngüsü oluşturmuyor.

## Sonraki adım

Model envanteri, sentetik sağlık kontrolü, karantina ve yeniden test yaşam döngüsünü proje profilinden ayrı bir katman olarak eklemek.
