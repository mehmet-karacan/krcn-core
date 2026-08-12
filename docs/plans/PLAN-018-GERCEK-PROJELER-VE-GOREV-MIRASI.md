# Plan 018 - Gerçek projeler ve görev mirası

## Durum

Bekliyor.

## Amaç

KRCN Core'un tamamlanmış mimarisini gerçek projeler üzerinde doğrulamak; eski MK-Hub kayıtlarından aktif ve geçmiş işleri ilgili proje kapsüllerine güvenli biçimde aktarmak.

## Hedef projeler

- `plsql-test-sync`
- `schema-compare-platform`
- `schema-transform-platform`
- `utplsql`

Fiziksel proje ve eski MK-Hub yolları makineye özel kullanıcı verisidir. Git'e yazılmaz; çalışma sırasında kullanıcı tarafından sağlanan yerel binding kayıtlarıyla çözülür.

## İş paketleri

1. Her projeyi salt okunur kaynak binding ile entegre et.
2. Tam discovery, bilgi çıkarımı, capability ve skill seçimi yap.
3. Kaynak kod indekslerini oluştur ve doğrula.
4. Eski MK-Hub kayıtlarını untrusted ve read-only kaynak olarak tara.
5. Geçmiş ve aktif görev adaylarını proje, durum ve kanıtlarına göre sınıflandır.
6. Belirsiz veya birden fazla projeye ait olabilecek kayıtları otomatik taşımadan inceleme listesine al.
7. Onaylanan kayıtları Work Graph içine provenance bilgisiyle yerleştir.
8. Aktif görevler için resume, geçmiş görevler için arşiv görünümü oluştur.
9. Proje bazlı test, kapsül, retrieval ve taşınabilirlik doğrulaması yap.

## Kabul ölçütleri

- Proje kaynak dosyaları KRCN home içine kopyalanmaz.
- Eski görev kaydı kanıtsız biçimde aktif göreve dönüştürülmez.
- Her aktarılan görev kaynak kaydı ve proje ilişkisi taşır.
- Dört proje birbirinden bağımsız kapsüllerde çalışır.
- `nerede kaldık` sorusu her proje için doğru aktif görev bağlamını verir.
