# Kaynak kod indeksi rebind düzeltmesi

## Durum

Tamamlandı.

## Bulgu

Kaynak kod indeksi özeti proje, binding kimliği ve source digest üzerinden güncellik kontrolü yapıyor, ancak binding revision değerini karşılaştırmıyordu. Sorgu aşaması binding revision eşleşmesini zorunlu tuttuğu için içerik değişmeden yapılan rebind sonrasında indeksleme no-op, arama ise stale sonucu veriyordu.

## Düzeltme

- İndeks özeti güncellik hesabına beklenen binding revision eklendi.
- Doğrudan indeksleme, proje entegrasyonu, apply doğrulaması ve resume özeti aynı revision değerini kullanacak şekilde bağlandı.
- Rebind sonrasında kaynak içeriği değişmediyse doğrulanmış parçalar yeniden kullanılıyor, ancak SQLite metadata ve index digest yeni binding revision ile yeniden yayımlanıyor.
- Rebind, stale arama, yeniden indeksleme ve başarılı arama zincirini doğrulayan uçtan uca regresyon testi eklendi.

## Korunan davranışlar

- Proje kaynağı kopyalanmıyor veya değiştirilmiyor.
- Değişmeyen kaynak parçaları gereksiz yere yeniden işlenmiyor.
- Sorgu aşamasındaki fail-closed stale kontrolü zayıflatılmıyor.
- Türetilmiş SQLite indeksi authoritative kaynak durumunun yerine geçmiyor.
