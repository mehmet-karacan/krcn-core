# Faz 21 - Model karar servisi

## Durum

Tamamlandı.

## Amaç

Model routing, envanter, sağlık, proje benchmarkı, maliyet ve gerçek çalışma
ölçümlerini tek kapalı döngü kararında birleştirmek.

## Tamamlananlar

- Model Decision Service için sürümlü policy ve katı parser eklendi.
- Güncel sağlık, karantina, benchmark ve inventory digestleri ortak eligibility
  kapısında birleştirildi.
- Benchmark, tarihsel başarı, gecikme ve maliyet için deterministik net değer
  skoru üretildi.
- Tarihli yerel fiyat kataloğu eklendi; core içine statik provider fiyatı
  gömülmedi.
- Fiyat kataloğu user-data, benchmark sonucu ve runtime gözlemi derived veri
  olarak exact-plan sınırına bağlandı.
- Gerçek çalışma gözlemleri sonraki karardaki başarı ve gecikme skoruna geri
  beslenir hale getirildi.
- `model.decide` tek iş yükünü, `model.decide-plan` ise TaskPlan'ın tüm
  adımlarını otomatik atar hale getirildi.
- Her plan adımı ayrı model assignment kimliği aldı.
- Bilinen worker modelinin verifier için yeniden kullanılması engellendi.
- Kanıt eksikliğinde maliyet veya başarı uydurmak yerine açık, skorsuz
  `client-default` fallback korundu.
- Karar, assignment ve kanıt kayıtlarının yetki vermediği sabitlendi.

## Korunan sınırlar

- Model veya provider çağrısı yapılmıyor.
- Credential, endpoint, prompt, response, kaynak içeriği ve fiziksel yol
  saklanmıyor.
- Provider, mutation, TaskPlan ve verifier yetki kapıları değişmiyor.
- Fiyat verisi versioned core policy içinde tutulmuyor.

## Sonraki adım

Retrieval kalite ve ölçek kararlarını gerçek golden soru kümesiyle ölç.
