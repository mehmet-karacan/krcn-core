# Plan 018 - Gerçek projeler ve görev mirası

## Durum

Devam ediyor.

## Amaç

KRCN Core'un tamamlanmış mimarisini gerçek projeler üzerinde doğrulamak; eski MK-Hub kayıtlarından aktif ve geçmiş işleri ilgili proje kapsüllerine güvenli biçimde aktarmak.

## Hedef projeler

- `plsql-test-sync`
- `schema-compare-platform`
- `schema-transform-platform`
- `utplsql`
- `sky-microservis`
- `sky-ui` kaynak dizini, keşfedilen proje kimliği `call-center-ui`

Fiziksel proje ve eski MK-Hub yolları makineye özel kullanıcı verisidir. Git'e yazılmaz; çalışma sırasında kullanıcı tarafından sağlanan yerel binding kayıtlarıyla çözülür.

## İş paketleri

1. Generated, vendor, binary, secret ve makineye özel kaynak sınıflarını merkezi policy ile dışla.
2. Her projeyi salt okunur kaynak binding ile entegre et.
3. Tam discovery, bilgi çıkarımı, capability ve skill seçimi yap.
4. Kaynak kod indekslerini oluştur ve doğrula.
5. Eski MK-Hub kayıtlarını untrusted ve read-only kaynak olarak tara.
6. Geçmiş ve aktif görev adaylarını proje, durum ve kanıtlarına göre sınıflandır.
7. Belirsiz veya birden fazla projeye ait olabilecek kayıtları otomatik taşımadan inceleme listesine al.
8. Onaylanan kayıtları Work Graph içine provenance bilgisiyle yerleştir.
9. Aktif görevler için resume, geçmiş görevler için arşiv görünümü oluştur.
10. Proje bazlı test, kapsül, retrieval ve taşınabilirlik doğrulaması yap.

## Kabul ölçütleri

- Proje kaynak dosyaları KRCN home içine kopyalanmaz.
- Eski görev kaydı kanıtsız biçimde aktif göreve dönüştürülmez.
- Her aktarılan görev kaynak kaydı ve proje ilişkisi taşır.
- Altı kaynak proje, keşfedilen güvenli proje kimlikleri altında birbirinden bağımsız kapsüllerde çalışır.
- `nerede kaldık` sorusu her proje için doğru aktif görev bağlamını verir.
