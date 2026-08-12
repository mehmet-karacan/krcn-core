# Faz 9 sürekli proje entegrasyonu tamamlandı

## Sonuç

`Projeyi entegre et` isteği artık yalnız proje kaydı ve dosya keşfiyle bitmiyor. Ortak `project.integrate` operasyonu yeni veya kayıtlı bir projede kayıt, tarama, bilgi tabanı, capability profili, hibrit vektör indeksi ve doğrulama aşamalarını tek exact planda yönetiyor.

## Tarama davranışı

- Açık `entegre et` isteği manuel tarama olarak kaydedilir ve her zaman salt okunur keşif yapar.
- Proje çalışması öncesindeki güncellik denetimi otomatik kip kullanır.
- Otomatik kip varsayılan 24 saatlik süre dolduğunda tarar.
- Bilgi kaydı, source state, capability profili veya doğrulama aşaması eksikse süre dolmadan tarama planlanır.
- Yalnız vektör indeksi eksikse güncel bilgi kataloğundan indeks onarılır ve gereksiz kaynak taraması yapılmaz.
- Tam ve güncel entegrasyon no-op olur.

## Bilgi ve capability profili

Keşif kanıtından authoritative source kaydı ile proje overview, structure, workflows ve capabilities bilgi kayıtları üretilir. Kayıtlar exact kaynak digest'ine bağlıdır. Kaynak değiştiğinde ilgili kayıtlar yeni revision ile güncellenir.

Planner, salt okunur worker ve verifier rolleri merkezi capability registry'den seçilir. Ortak keşif, bilgi çıkarma ve hibrit retrieval skill'lerine ek olarak keşfedilen teknoloji skill'leri eklenir. Seçim yeni yetki vermez ve kullanıcı policy'lerini değiştirmez.

## Vektör ve RAG

Onaylı bilgi kataloğu SQLite FTS ve 192 boyutlu deterministik vektör kullanan hibrit indekse yazılır. Çevrimdışı profil `deterministic-hashing` olarak kaydedilir. Qwen3 ve BGE-M3 sıralaması korunur ancak gerçek proje içeriği ayrı session onayı olmadan uzak providera gönderilmez.

## Gerçek proje doğrulaması

`gpu-fusion` üzerinde manuel tam entegrasyon uygulandı:

- 1.752 dosya salt okunur keşfedildi.
- Java ve Node.js teknolojileri doğrulandı.
- Beş kanıta bağlı bilgi kaydı oluşturuldu.
- Java ve Node.js skill'leri capability profiline eklendi.
- Beş girdili hibrit indeks oluşturuldu ve SQLite bütünlük kontrolünden geçti.
- Kaynak proje dosyalarının boyut ve zaman snapshot'ı değişmedi.
- Hemen sonraki otomatik denetim no-op oldu.
- Sonraki otomatik tarama zamanı 24 saat sonrası olarak hesaplandı.
- Gerçek hibrit sorgu beş güncel proje kaydını döndürdü.

## Korunan sınırlar

- Proje kaynakları KRCN Core veya KRCN home içine kopyalanmadı.
- Proje kaynak dosyaları değiştirilmedi.
- Secret değeri, fiziksel kaynak yolu veya veritabanı satırı bilgi kayıtlarına alınmadı.
- Kullanıcı verisi exact plan ve açık onay olmadan yazılmadı.
- Uzak embedding provider kullanılmadı.
- Eksik veya yarım kalan aşamalar sonraki entegrasyon planında onarılabilir kaldı.
