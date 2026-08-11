# PLAN-004 - Güvenli merge into motoru

## Durum

Tamamlandı. On adımın tamamı doğrulandı ve Faz 3 baseline'ı oluşturuldu.

## Amaç

Yeni bir KRCN Core release paketini mevcut kuruluma; kullanıcı verisini, secret'ları, yerel değişiklikleri ve yönetilmeyen dosyaları koruyarak uygulayan inspection, diff, dry-run, backup, merge, migration, verify ve rollback akışını oluşturmak.

## Değişmez sınırlar

- Release paketi yalnızca manifestte açıkça tanımlanmış core dosyalarını taşıyabilir.
- User-data, secrets, runtime ve unmanaged içerik release payload'ına giremez.
- Fiziksel kurulum ve release yolları genel planlara veya deployment kayıtlarına yazılmaz.
- Diff ve dry-run hiçbir dosyayı değiştirmez.
- Apply yalnızca daha önce görülen plan kimliği birebir eşleştiğinde çalışır.
- Değiştirilecek veya kaldırılacak her mevcut dosya uygulamadan önce doğrulanmış backup'a alınır.
- Yerel olarak değiştirilmiş managed core dosyası sessizce ezilmez; conflict üretilir.
- Kullanıcıya ait policy anlamı migration veya core güncellemesiyle zayıflatılamaz.
- Secret değerleri okunmaz, kopyalanmaz, loglanmaz veya backup manifestine yazılmaz.
- Zorunlu verify başarısız olursa aynı deployment otomatik rollback ile geri alınır.
- Release manifestindeki içerik çalıştırılabilir komut olarak kabul edilmez.
- Bütün testler ağ kapalı ve sentetik kurulumlar üzerinde çalışır.

## Uygulama adımları

### Adım 1 - Faz bağlamı ve sürüm sözleşmeleri

- Faz 3 current-work kaydını ve uygulama sırasını oluştur.
- Release manifest ve installation state şemalarını tanımla.
- Faz 2 baseline'ını değişmez giriş noktası olarak bağla.

### Adım 2 - Installation inspection

- Kurulum kimliği, aktif core sürümü ve managed dosya durumunu salt okunur incele.
- Sahiplik sınıflarını ve kesintiye uğramış deployment kayıtlarını raporla.
- Fiziksel yolları genel çıktıdan çıkar.

### Adım 3 - Release ve compatibility doğrulaması

- Release manifestini katı alan, sürüm ve path kurallarıyla doğrula.
- Payload hash ve boyutlarını manifestle karşılaştır.
- Güvenilen manifest digest'i olmadan release'i uygulanabilir kabul etme.
- Aktif sürümün compatibility aralığında olduğunu doğrula.

### Adım 4 - Ownership-aware diff ve conflict

- Release ile kurulum arasındaki create, update, delete ve unchanged farklarını üret.
- Her hedefi ownership manifestiyle sınıflandır.
- Yerel managed değişiklikleri ve sahiplik ihlallerini conflict olarak raporla.

### Adım 5 - Exact-plan merge dry-run

- Diff sonucunu mutation planları ve tek bir merge plan kimliğiyle bağla.
- Conflict, migration ve derived etkilerini kullanıcıya açık biçimde göster.
- Plan sonradan değişirse apply işlemini reddet.

### Adım 6 - Backup ve deployment journal

- Uygulama öncesinde etkilenen managed dosyalar ile installation state'i backup'a al.
- Backup içeriklerini hashlerle doğrula.
- Kesintiyi algılayacak deployment durum kaydını oluştur.

### Adım 7 - Managed apply ve migration

- Yalnızca doğrulanmış release payload'ını atomic write ile uygula.
- Delete işlemini yalnızca backup ve gerekli onay varsa gerçekleştir.
- Yalnızca trusted core registry'de bulunan sürümlü ve tekrar çalıştırılabilir migration'ları çalıştır.

### Adım 8 - Derived, verify ve rollback

- Tanımlı derived action'ları trusted registry üzerinden çalıştır.
- Managed dosya hashleri ve korunan kayıtlar için post-merge verify uygula.
- Başarısız verify veya açık rollback isteğinde backup'tan geri dön.

### Adım 9 - CLI ve ortak istemci servisleri

- Inspect, diff, merge, verify ve rollback işlemlerini ortak application service'e bağla.
- CLI, SDK, MCP, plugin ve yapay zekâ istemcilerinin aynı güvenlik davranışını kullanmasını sağla.

### Adım 10 - Entegrasyon testleri ve kapanış

- Temiz, mevcut, yerel değişiklikli, kesintili ve hatalı release senaryolarını hermetik test et.
- Kullanıcı verisi, policy, secret reference ve unmanaged dosyaların korunduğunu kanıtla.
- Faz 3 baseline manifestini ve kapanış raporunu oluştur.

## Kabul ölçütleri

- Release, güvenilen manifest digest'i ve eksiksiz payload doğrulaması olmadan uygulanamamalı.
- Mevcut kurulum salt okunur inspection ile yeniden üretilebilir biçimde tanımlanabilmeli.
- Dry-run planı create, update, delete, conflict, migration ve derived etkilerini göstermeli.
- Apply eski veya farklı plan kimliğiyle başlamamalı.
- Managed core dosyaları atomic olarak güncellenmeli.
- User-data, secret ve unmanaged dosyalar değişmeden kalmalı.
- Yerel managed değişiklik conflict olarak korunmalı.
- Migration'lar versioned, registry kontrollü ve idempotent olmalı.
- Zorunlu verify başarısızlığında otomatik rollback tamamlanmalı.
- Açık rollback daha önce tamamlanmış deployment'ı geri alabilmeli.
- Aynı release'in tekrar uygulanması veri değişikliği üretmemeli.
- Tüm istemciler aynı application service ve güvenlik kapılarını kullanmalı.

## Onay kapıları

Sentetik release ve geçici kurulumlar üzerinde bütün akış geliştirilebilir. Gerçek kurulum apply işlemi, core delete etkisi, user-data migration'ı, gerçek integration doğrulaması veya uzak release erişimi ayrı dry-run ve geçerli kullanıcı onayı gerektirir.
