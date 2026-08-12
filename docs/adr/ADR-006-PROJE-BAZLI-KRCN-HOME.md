# ADR-006 - Proje bazlı KRCN_HOME

## Durum

Kabul edildi. Faz 8 içinde kademeli olarak uygulanacaktır.

## Bağlam

Mevcut taşınabilirlik modeli KRCN kullanıcı evini core repository'sinden ve dış proje dizinlerinden ayrı bir merkezi konumda tutar. Bu ayrım core güncellemelerini güvenli hale getirir ancak kullanıcının bir projeye ait işler, belgeler, kararlar, policy'ler, entegrasyon kayıtları ve yerel çalışma verilerini proje ile birlikte bulmasını zorlaştırır.

Kullanıcı proje dizininde çalışırken KRCN bağlamının doğal olarak aynı proje altında bulunmasını, Git tarafından izlenmemesini ve gerektiğinde farklı bir fiziksel konum seçebilmeyi istemektedir.

## Karar

1. Proje kapsamındaki varsayılan KRCN kullanıcı evi `<proje-kökü>/.krcn` olacaktır.
2. İlk initialization işleminde sistem önerilen fiziksel konumu gösterecek ve kullanıcıdan varsayılanı kabul etmesini, farklı bir ana dizin seçmesini veya işlemi iptal etmesini isteyecektir.
3. Kullanıcı farklı bir ana dizin seçerse KRCN çalışma alanı bu dizinin `.krcn` alt dizininde oluşturulacaktır.
4. Açık `data_root` veya `KRCN_HOME` yapılandırması exact path olarak değerlendirilecek ve geriye dönük uyumluluk için önceliğini koruyacaktır.
5. Konum seçimi user-data mutation işlemidir. Salt okunur resolution ve dry-run yapılmadan dizin oluşturulmayacaktır.
6. `.krcn` Git tarafından izlenmeyecek, discovery kapsamına girmeyecek ve uzak servislere otomatik gönderilmeyecektir.
7. Source binding proje içeriği için salt okunur kalacaktır. KRCN'nin yönettiği `.krcn` kontrol alanı proje kaynağından ayrı bir sahiplik sınırı olarak değerlendirilecektir.
8. KRCN proje kaynaklarını, dış belgeleri veya harici veritabanlarını `.krcn` içine kopyalamayacaktır.
9. Git clone işlemi `.krcn` verisini geri getirmediği için backup ve restore ayrı bir kullanıcı akışı olarak kalacaktır.
10. Mevcut merkezi kullanıcı evleri otomatik taşınmayacak; migration ayrı, yedekli, exact-plan onaylı ve geri alınabilir olacaktır.

## Sonuçlar

- Kullanıcı bir projeye ait KRCN bağlamını proje diziniyle birlikte bulabilecektir.
- Proje içinde çalışan CLI, Codex, Claude ve plugin'ler aynı varsayılan konumu çözümleyebilecektir.
- `.krcn` oluşturmak dış proje ağacında kontrollü bir metadata mutation işlemidir ve eski mutlak no-write varsayımına açık bir istisna getirir.
- Proje yalnız Git üzerinden yeniden klonlandığında yerel KRCN verileri bulunmayacaktır; sistem bunu eksik veri yerine restore gereksinimi olarak raporlayacaktır.
- Özel konum seçen kullanıcı proje klasörünü tek başına kopyalamanın KRCN verilerini taşımayacağı konusunda bilgilendirilecektir.
- Faz 6 yerleşiminden geçiş layout version artışı ve geriye dönük uyumluluk testleri gerektirecektir.
