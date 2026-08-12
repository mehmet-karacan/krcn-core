# Plan 011 - Sürekli proje entegrasyonu

## Amaç

`Projeyi entegre et` isteğini yalnız kayıt ve dosya keşfi yapan bir komut olmaktan çıkarıp projenin kullanılabilir KRCN bağlamını tamamlayan tek yaşam döngüsüne dönüştürmek.

## Kullanıcı sözleşmesi

Kullanıcı yalnız proje dizinini ve `entegre et` niyetini verir. KRCN teknik alt adımları kendisi belirler. Kayıtlı bir proje yeniden entegre edildiğinde işlem erken bitmez; eksik veya eski aşamalar bulunur ve exact planda gösterilir.

## Tarama kipleri

1. Kullanıcının `entegre et`, `tara`, `yeniden tara` veya `güncelle` isteği manuel taramadır.
2. Normal proje çalışması öncesindeki güncellik denetimi otomatik taramadır.
3. Otomatik tarama varsayılan 24 saatlik güncellik süresi dolduğunda çalışır.
4. Zorunlu entegrasyon aşaması eksikse süre dolmamış olsa da otomatik tarama planlanır.
5. Güncel ve tam entegrasyon no-op olur.
6. Otomatik karar, kullanıcı verisi veya uzak provider onayını geçersiz kılmaz.

## Tam entegrasyon aşamaları

1. Proje kaydı ve salt okunur source binding.
2. Kaynak keşfi ve revision-aware source state.
3. Kanıta bağlı authoritative source ve proje bilgi kayıtları.
4. Teknolojiye göre rol ve skill profili.
5. SQLite FTS ve yerel deterministik vektör indeksi.
6. Bütünlük ve kullanılabilirlik doğrulaması.

## Kalıcı durum

Her proje için tarama sırası, son tarama kipi, tarama nedeni, güncellik süresi, kaynak digest'i, bilgi digest'i, embedding profili, rol ve skill referansları ile tamamlanan aşamalar korunur. Son başarılı tarama zamanı, doğrulanmış entegrasyon durumu dosyasının yazılma zamanından elde edilir.

## Güvenlik sınırları

- Harici proje dosyaları yerinde ve salt okunur kalır.
- Proje kaynakları KRCN home içine kopyalanmaz.
- Bilgi kayıtları secret benzeri alan kabul etmez.
- Kullanıcı verisi mutasyonları exact plan ve açık onay gerektirir.
- Uzak embedding kullanımı ayrı session onayı olmadan başlamaz.
- Çevrimdışı deterministik vektör fallback her zaman kullanılabilir kalır.
- Eksik veya yarım entegrasyon bir sonraki çalıştırmada onarılabilir olmalıdır.

## Uygulama adımları

1. Entegrasyon durum ve plan şemalarını ekle.
2. Manuel ve otomatik tarama kararını ortak policy ile tanımla.
3. `project.integrate` application operasyonunu ekle.
4. Doğal dil yönlendirmesinde `entegre et` niyetini tam yaşam döngüsüne bağla.
5. Kanıta bağlı proje profili ve bilgi kayıtlarını üret.
6. Teknolojiye uygun planner, worker, verifier ve skill referanslarını seç.
7. Hibrit vektör indeksini eksik veya eski olduğunda yeniden oluştur.
8. Yeni entegrasyon, no-op, süre aşımı ve eksik aşama onarımını test et.

## Tamamlanma ölçütleri

- Yeni bir proje tek exact planla tam entegrasyon adımlarını hazırlayabilmeli.
- Kayıtlı bir projedeki eksik bilgi veya indeks yeniden oluşturulabilmeli.
- Manuel ve otomatik tarama sonucu makine tarafından okunabilir olmalı.
- 24 saat dolmamış tam entegrasyon no-op olmalı.
- 24 saat dolmuş entegrasyon otomatik tarama planlamalı.
- Proje değişikliği bilgi kayıtları ve vektör indeksine yansımalı.
- Kaynak dosyaların byte ve zaman bilgileri KRCN tarafından değiştirilmemeli.
