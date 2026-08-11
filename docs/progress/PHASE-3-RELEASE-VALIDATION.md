# Faz 3 release doğrulaması

## Amaç

Bir release paketini diff veya apply öncesinde manifest güveni, sürüm uyumluluğu, ownership, payload bütünlüğü ve repository güvenlik politikası açısından doğrulamak.

## Uygulanan davranış

1. Release manifest yalnızca tanımlı alanları ve katı veri türlerini kabul eder.
2. Manifest canonical JSON üzerinden SHA-256 digest üretir.
3. Caller tarafından bağımsız kanaldan sağlanan trusted digest birebir eşleşmeden paket kabul edilmez.
4. Aktif core sürümü manifestteki minimum ve maximum compatibility aralığında olmalıdır.
5. Merge üzerinden daha düşük core sürümüne geçiş reddedilir.
6. Her release hedefi ownership manifestinde `core` olarak çözülmelidir.
7. Upsert dosyaları tam byte boyutu ve SHA-256 kanıtıyla doğrulanır.
8. Delete girdileri beklenen önceki managed hash değerini taşır.
9. Payload yalnızca manifestteki upsert dosyalarını içerebilir; ek dosya ve symlink reddedilir.
10. Payload secret, makine yolu, engellenmiş dosya ve uzun tire taramasından temiz geçmelidir.
11. Migration ve derived action değerleri yalnızca portable kimliktir; komut olarak çalıştırılmaz.
12. Genel release özeti fiziksel release yolunu içermez.

## Güven sınırı

Release dizininin kendi içinden okunan digest güven kanıtı sayılmaz. Caller trusted digest değerini ayrı bir kanaldan sağlamalıdır. Faz 3 baseline'ı uzak release indirmez ve ağ kullanmaz.

## Sonraki adım

Doğrulanmış release ile installation inspection karşılaştırılarak create, update, delete, unchanged ve conflict sınıfları üretilecek.
