# Paket 2 CLI davranış envanteri

## Amaç

Mevcut CLI'ın hangi verileri okuduğunu, nerelere yazdığını, hangi dış sistemlere bağlanabildiğini ve yeni core sözleşmelerine aktarılırken hangi davranışların korunup hangilerinin yeniden tasarlanacağını belirlemek.

## İnceleme yöntemi

CLI kaynağı salt okunur olarak incelendi. Kaynak kod, yerel yol, kullanıcı verisi, bağlantı bilgisi veya secret depoya aktarılmadı. Sonuçlar yalnızca taşınabilir komut ve etki sınıfları olarak `.ai/legacy-cli-inventory.json` içinde kaydedildi.

## Envanter özeti

- 28 genel komut ve 1 dahili worker olmak üzere 29 komut kaydedildi.
- Her komut için okunan ve yazılan sahiplik sınıfları belirlendi.
- Ağ ve dış sistem etkileri ayrı kaydedildi.
- Korunabilecek davranışlarla yeniden tasarlanması veya ertelenmesi gereken davranışlar ayrıldı.

| Komut ailesi | Temel etki | Karar |
| --- | --- | --- |
| Proje ve görev | User-data okuma ve yazma | Mutasyonlar yeniden tasarlanacak |
| Index ve memory | Derived veri üretimi, olası provider kullanımı | Ağ ve sahiplik denetimi eklenecek |
| Veri tabanı index | Dış veri tabanı okuma, derived veri üretimi | Policy enforcement sonrasına ertelendi |
| Lock | Runtime yazma ve silme | Sahiplik ve onay teknik olarak uygulanacak |
| Arama, skill ve durum | Çoğunlukla salt okunur | Güvenli olanlar korunacak |
| Handoff | Varsayılan okuma, isteğe bağlı user-data yazma | Çıktı sahipliği ayrıştırılacak |

## Kritik bulgular

1. Bazı proje komutları kayıt oluşturmanın yanında dış kaynak dizinine de dosya yazabiliyor. Bu davranış açık hedef, dry-run ve kullanıcı onayı olmadan korunmayacak.
2. Index ve semantik arama akışları provider bilgisini ortamdan kendiliğinden bulabiliyor. Yeni yapıda ağ varsayılan olarak kapalı olacak ve içerik gönderimi açık onay gerektirecek.
3. Veri tabanı index akışı çoğunlukla metadata sorguları çalıştırsa da bir sağlayıcıda `SELECT` olmayan session komutu kullanıyor. Kullanıcının "yalnızca SELECT" politikası etkinse bu komut da engellenecek. Salt okunur niyet, statement seviyesindeki kısıtı geçersiz kılamaz.
4. Core, runtime, user-data ve derived içerik aynı fiziksel ağaçta karışabiliyor. Yeni yapıda her yazma işleminden önce sahiplik sınıfı çözülecek.
5. Lock kaldırma ve zorla kaldırma akışlarında sahiplik ile insan onayı teknik bir kanıtla uygulanmıyor. Yeni uygulamada yalnızca komut adı onay sayılmayacak.
6. Bazı çıktılar makineye özel mutlak yolları gösterebiliyor. Taşınabilir core çıktıları göreli kimlik ve güvenli source binding kullanacak.

## Kullanıcı politikasını koruma kararı

Kullanıcının veri tabanında yalnızca `SELECT` istemesi gibi açık veya onaylanmış kalıcı kısıtlar user-data olarak saklanacak. Core güncellemesi bu kayıtları ezemeyecek, zayıflatamayacak veya default değerle değiştiremeyecek. Bu sözleşme şimdi tanımlandı; gerçek doğrulama ve etkili policy değerlendirme motoru arındırılmış CLI çalışmasının ilk güvenlik kapılarından biri olacak.

## Doğrulama

- Envanterde 29 benzersiz komut kimliği bulunuyor.
- Kaynak kod aktarılmadığı makine sözleşmesiyle doğrulanıyor.
- Ağ etkisi olan hiçbir komut doğrudan korunacak olarak işaretlenmedi.
- Yazma davranışı olan her komutun yazdığı sahiplik sınıfları açıkça kayıtlı.
- Kritik veri tabanı, dış kaynak yazma ve lock onayı riskleri kabul testleriyle korunuyor.

## Sonraki adım

CLI kaynağı Git dışındaki staging alanında arındırılacak. Önce context çözümleme, sahiplik kontrolü, ağ onayı ve kullanıcı policy değerlendirme sınırları eklenecek. Kaynak kod ancak inceleme ve kullanıcı onayından sonra takip edilen depo ağacına alınacak.
