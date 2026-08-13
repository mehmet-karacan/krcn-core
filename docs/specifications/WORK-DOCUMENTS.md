# Work Documents

## Amaç

Work Documents, bir projeye ait talep, defect ve görev belgelerini proje kaynak kodundan ayrı biçimde saklar. Belgeler kullanıcı verisidir. Kaynak kodu, repository dosyaları ve veritabanı satırları bu alana kopyalanmaz.

## Yerleşim

```text
.krcn/projects/<project-id>/local-data/work-documents/
  requests/<year>/<id>/source/<source-id>/...
  defects/<year>/<id>/source/<source-id>/...
  tasks/<active|archived>/<id>/source/<source-id>/...
  shared/requests/<year>/<combined-id>/source/<source-id>/...
  _krcn/import-manifest.json
```

`source` altında kullanıcının özgün belgeleri bulunur. KRCN tarafından üretilen kayıtlar `_krcn` altında tutulur. Belgeler taşınırken kaynak dizin silinmez, değiştirilmez veya yeniden adlandırılmaz.

## İşleme zinciri

`gpu-fusion gelen işlerini işle` isteği şu zinciri exact plan üzerinden çalıştırır:

1. Belge manifestini ve dosya digestlerini doğrular.
2. Belgeleri ilgili Work Item kayıtlarına portable referans ve digest ile bağlar.
3. Work Graph SQLite projeksiyonunu yeniler.
4. Yerel semantik iş indeksini artımlı olarak yeniler.
5. Ham belge içeriğini Work Graph veya vektör SQLite dosyasına kopyalamaz.

Büyük, binary veya hassas bulgulu dosyalar korunur ancak `metadata-only` ya da `excluded-sensitive` olarak işaretlenir. Uzak modele örtülü veri aktarımı yapılmaz.

## Taşınabilirlik

Tüm `.krcn` dizini kullanıcı yedeği olarak taşınabilir. Standart proje kapsülü ham Work Documents içeriğini dışlar ve yeniden bağlanması gereken yerel bağımlılık olarak bildirir. Böylece portable kapsül içinde kaynak belge veya makine yolu sızıntısı oluşmaz.
