# Faz 18 proje özel mikro benchmark paketi

## Durum

Tamamlandı.

## Sonuç

KRCN artık güncel ve eksiksiz proje yetkinlik profilinden proje özel mikro benchmark paketi üretebiliyor. Her uzman iş yükü ayrı bir vaka olarak tanımlanıyor ve vaka, kaynak metni yerine doğrulanmış yetkinlik, modül ve kanıt kimliklerine bağlanıyor.

Paket oluşturmak model çağrısı yapmıyor. Proje kodunu çalıştırmıyor, kaynak dosyayı değiştirmiyor ve prompt metni saklamıyor.

## Uygulanan sınırlar

- Yalnız tam ve model ataması için güvenilir proje profili kabul ediliyor.
- Binding revision, source digest ve evidence dosya özetleri yeniden doğrulanıyor.
- Her workload için sürümlü şablon, çıktı sözleşmesi ve değerlendirme ölçütü üretiliyor.
- Kalite yüzde 80, yanıt güvenilirliği yüzde 10 ve süre yüzde 10 ağırlık taşıyor.
- Veri tabanı analizi `local-only` olarak işaretleniyor.
- Uzak çalıştırmaya uygun görünen vaka bile sağlayıcı onayı kazanmıyor.
- Vaka bağlamı policy sınırını aşarsa sessiz kırpma yapılmıyor ve işlem reddediliyor.
- Her vaka ve bütün paket deterministik digest taşıyor.
- Aynı proje profili ve policy ile tekrar üretim no-op kalıyor.
- Profil veya policy değişirse önceki paket `stale` görünüyor.
- Paket proje kapsülünün türetilmiş alanında tutuluyor ve başka projeyle karışmıyor.

## Test sonucu

Fazın hedefli testleri proje entegrasyonu, içeriksiz paket üretimi, exact-plan, yerel veri tabanı vakası, no-op, digest kurcalaması, eksik proje reddi ve güvenli listeleme davranışlarını doğruluyor.

## Sonraki adım

Sağlığı geçmiş modelleri bu paketlerde gerçekten çalıştıran benchmark runner, ölçüm kaydı, minimum başarı eşiği ve proje özel birincil/yedek model ataması.
