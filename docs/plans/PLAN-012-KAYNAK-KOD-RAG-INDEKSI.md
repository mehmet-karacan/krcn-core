# Plan 012 - Kaynak kod RAG indeksi

## Amaç

Kayıtlı projelerin desteklenen kaynak dosyalarını proje dizininde ve salt okunur tutarak sınıf, metot, sembol ve kod parçası seviyesinde aranabilir hale getirmek.

## Kullanıcı sözleşmesi

Kullanıcı `projeyi entegre et` dediğinde kaynak kod indeksi de tam entegrasyonun parçası olur. Ayrı bir teknik komut veya `vektörle` ifadesi gerekmez. İndeks eksik ya da kaynak digest'ine göre eskiyse entegrasyon planı bu aşamayı kendisi ekler.

## Güvenlik sınırı

- Proje kaynak dosyaları KRCN Core veya KRCN home içine kopyalanmaz.
- SQLite indeksinde ham kod metni ve fiziksel proje yolu saklanmaz.
- İndeks yalnız göreli yol, dil, satır ve karakter aralığı, içerik hash'i, güvenli sembol adları ve vektörleri tutar.
- Arama sonucu istenirse ilgili kod parçasını hash doğrulamasından sonra gerçek proje dosyasından anlık okur.
- Uzak embedding sağlayıcısına kod gönderimi ayrı session onayı olmadan başlamaz.

## Uygulama adımları

1. Kaynak kod indeks policy'sini ve makinece doğrulanan şemaları ekle.
2. Desteklenen metin tabanlı kaynak ve yapılandırma dosyalarını seç.
3. Dosyaları örtüşmeli, satır kanıtı taşıyan deterministik parçalara ayır.
4. Ham metni saklamadan her parça için çevrimdışı vektör ve sembol metadatası üret.
5. Değişmeyen dosyaların parçalarını yeniden kullan, değişenleri yenile ve silinenleri çıkar.
6. SQLite indeksini staging, bütünlük kontrolü ve atomik değiştirme ile uygula.
7. Proje, dil ve göreli yol filtreli kaynak kod aramasını ortak application servisine ekle.
8. `project.integrate`, resume özeti, CLI ve istemci başlangıç bağlamına bağla.
9. Sentetik projelerde artımlı güncelleme, stale kapanışı ve no-copy sınırını test et.
10. `gpu-fusion` üzerinde gerçek indeks oluşturup arama kalitesini ve kaynak korunmasını doğrula.

## Tamamlanma ölçütleri

- Desteklenen tüm kaynak dosyalar indeks planında görünür olmalı.
- Her arama sonucu göreli dosya yolu ve kesin satır aralığı taşımalı.
- Ham kaynak kod SQLite dosyasında bulunmamalı.
- Değişmeyen dosyalar yeniden vektörlenmemeli.
- Değişen, eklenen ve silinen dosyalar bir sonraki entegrasyona doğru yansımalı.
- Stale indeks yanlış kod döndürmek yerine kapalı biçimde yeniden entegrasyon istemeli.
- Proje kaynaklarının byte ve zaman bilgileri KRCN tarafından değiştirilmemeli.
