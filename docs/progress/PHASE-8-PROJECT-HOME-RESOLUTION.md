# Faz 8 proje çalışma alanı çözümleme

## Sonuç

Proje bazlı KRCN kullanıcı evi için hiçbir dizin veya kullanıcı verisi oluşturmayan ortak resolution katmanı hazırlandı.

## Çözümleme sırası

1. Açık verilen exact `data_root`.
2. Geriye dönük uyumlu exact `KRCN_HOME` ortam değeri.
3. Daha önce onaylanmış proje konumu.
4. `<proje-kökü>/.krcn` varsayılan önerisi.

Varsayılan öneri kullanıcı kararı gerektirir ve `use-default`, `choose-parent` veya `cancel` seçeneklerini taşır. Kullanıcı başka bir ana dizin seçtiğinde hedef bu dizinin `.krcn` alt dizini olarak çözülür.

## Güvenlik davranışı

- Resolver yalnız mutlak ve güvenli dizin yollarını kabul eder.
- Dosya sistemi kökü, symbolic link ve dosya hedefleri reddedilir.
- Salt çözümleme sırasında hiçbir dizin oluşturulmaz.
- Public özet fiziksel yolu gizler.
- Yerel istemci kullanıcıya konumu göstermek istediğinde aynı typed sonuç açık path ile üretilebilir.
- Proje içindeki hedefler sonraki initialization adımı için Git kontrolü gerektirir.
- Git clone ve backup sınırları makinece okunabilir warning kodlarıyla taşınır.

## Korunan alanlar

- Mevcut `resolve_user_home` davranışı değiştirilmedi.
- Gerçek proje veya kullanıcı verisine yazılmadı.
- Merkezi kullanıcı evleri otomatik taşınmadı.
- Proje kaynakları discovery veya mutation işlemine alınmadı.
