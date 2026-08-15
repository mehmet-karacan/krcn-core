# Faz 21 - Taşınabilir proje kimliği

## Durum

Tamamlandı.

## Amaç

Proje dizini taşındığında aynı kaynağı yeni revision, diverged clone ve ilgisiz
kaynaktan ayırmak; yalnız doğrulanmış aynı içerik için locator-only exact rebind
uygulamak.

## Tamamlananlar

- Dört durumlu source relocation sınıflandırması eklendi.
- Aynı logical identity, digest ve dosya sayısı için `relocated-same-source`
  kararı üretildi.
- Değişen içerik, reviewed history kanıtı olmadan fail-closed hale getirildi.
- Linear history, diverged history ve unrelated history ayrı index eylemlerine
  bağlandı.
- Exact rebind yalnız locator değişikliğine izin verecek biçimde sertleştirildi.
- Aktif locator ile aynı dizine rebind açık hata olarak reddedildi.
- Public planlardan fiziksel aday yolu çıkarıldı ve sınıflandırma digest ile
  kanıtlandı.
- Değişmeyen kaynak için index evidence reuse, değişen revision için stale ve
  rebuild sınırı normatif hale getirildi.
- Repository context ve V1 architecture contract yeni sınıflandırmaya bağlandı.

## Doğrulama

- Dört sınıflandırma ve birbirinden farklı index eylemleri test edildi.
- Digest değişimi ve eksik history kanıtı negatif test edildi.
- Exact rebind planı ve relocation assessment JSON şemaları doğrulandı.
- Aday fiziksel yolun public çıktıda bulunmadığı doğrulandı.
- Mevcut binding revision ve source-code index reuse regresyonları korundu.

## Kapsam sınırı

Bu paket Git fetch yapmaz, ancestry bilgisi uydurmaz ve changed revision için
otomatik rebind uygulamaz. Linear veya diverged ilişki ayrı read-only adapter
kanıtıyla gelmeli; entegrasyon ve reconciliation kendi exact plan sınırlarını
korur.

## Sonraki adım

Model yetenek koruma kapısını ve golden karşılaştırmayı eklemek.
