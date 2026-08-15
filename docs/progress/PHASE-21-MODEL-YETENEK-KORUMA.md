# Faz 21 - Model yetenek koruma

## Durum

Tamamlandı.

## Amaç

KRCN güvenlik ve bağlam kurallarının modelin gerçek görev başarısını düşürmesini
engellemek; hard güvenlik sınırları ile soft yöntem rehberini machine-readable
biçimde ayırmak ve A/B golden karşılaştırmasıyla ölçmek.

## Tamamlananlar

- Yetki, kanıt, çıktı, secret ve side-effect sınırları bloklayıcı hard constraint
  olarak donduruldu.
- Çözüm yöntemi, araştırma sırası, alternatif, karşı kanıt, varsayım sorgulama ve
  lazy retrieval soft guidance olarak ayrıldı.
- Minimum context, lazy retrieval, full-history kapalı ve private chain-of-thought
  saklamama kuralları policy haline getirildi.
- Prompt ve source içermeyen beş vakalık kontrollü golden set eklendi.
- Baseline ve KRCN-enabled execution ölçümlerini karşılaştıran deterministik gate
  eklendi.
- Genel başarı ve skor regresyonu en fazla 200 basis point ile sınırlandı.
- Kritik regresyon ve hard constraint ihlali sıfır toleranslı hale getirildi.
- Token, latency, agent çağrısı ve insan müdahalesi farkları advisory olarak
  görünür hale getirildi.
- Evaluation çıktısı policy, golden set ve normalized ölçüm digestlerine bağlandı.

## Doğrulama

- Policy ve golden set public JSON şemalarıyla doğrulandı.
- Hard sınır kaldırma ve 200 basis point eşiğini gevşetme reddedildi.
- Eşit yetenek sonucu, genel başarı regresyonu, kritik skor regresyonu ve hard
  constraint ihlali test edildi.
- Maliyet overhead'inin görünür olduğu fakat güvenlik kararını gevşetmediği
  doğrulandı.
- Eksik golden vaka, invalid ölçüm, kapsam dışı ihlal, aggregate tamper, raw
  prompt ve raw output alanı fail-closed test edildi.

## Kapsam sınırı

Bu paket model veya provider çağırmaz ve route seçmez. Gerçek execution runner ve
proje bazlı model ataması daha sonraki Model Decision Service paketinde bu gate'i
kanıt olarak kullanacaktır.

## Sonraki adım

Generic akışta bağımsız verifier execution identity zorunluluğunu güçlendirmek.
