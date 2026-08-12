# Faz 8 veri bütünlüğü

## Sonuç

Deployment durum algılama, prosesler arası kayıt yarışı ve memory staleness açıkları kapatıldı. Backup ve migration kesinti senaryoları ek regresyon testleriyle korundu.

## Deployment durumu

- Gerçek state machine içinde bulunmayan `backing-up` değeri yarım işlem listesinden çıkarıldı.
- `failed` durumu kurtarma gerektiren yarım deployment olarak sınıflandırıldı.
- `completed` ve `rolled-back` dışındaki bütün geçerli durumlar yarım işlem olarak raporlanıyor.
- Bilinmeyen journal durumu sessizce geçilmiyor ve inspection fail-closed davranıyor.

## Eş zamanlı kayıt yazımı

- Her logical kayıt için prosesler arası advisory lock eklendi.
- Revision kontrolü lock alındıktan sonra yeniden yapılıyor.
- Aynı revision üzerinden başlayan iki ayrı prosesin ikisi birden başarılı olamıyor.
- Kazanan yazar revision 1 kaydını atomik olarak oluşturuyor; diğer yazar stale revision hatası alıyor.
- Lock dosyaları runtime koordinasyon verisi olarak kalıyor ve portable backup içine alınmıyor.

## Memory tazeliği

Context hazırlama artık memory kayıtlarının evidence içindeki source revision ve digest değerlerini current authoritative source ile karşılaştırıyor. Kaynak değişmiş, eksik veya geçersizse memory `stale` kabul ediliyor ve context dışında bırakılıyor. Böylece onaylanmış fakat dayandığı kaynak eskimiş bir bilgi güncelmiş gibi modele verilmiyor.

Rescan kendiliğinden arka planda çalışmıyor. Kaynak değişikliğinin authoritative revision kaydına yansıması için kullanıcı veya istemci explicit rescan akışını çalıştırıyor.

## Kesinti ve bozulma testleri

- Bozulmuş backup arşivi boş hedefte hiçbir dizin oluşturmadan reddediliyor.
- Restore sırasında kesilen project-home migration backup arşivini ve eski kaynağı koruyor.
- Başarısız hedef için eklenen Git exclude içeriği eski byte değerine geri alınıyor.
- Dolu restore hedefi ve post-plan değişiklikleri korunarak reddediliyor.
- Başarısız rollback journal durumu installation inspection içinde görünür kalıyor.

Gerçek kullanıcı verisi, gerçek backup veya gerçek deployment üzerinde mutation yapılmadı.
