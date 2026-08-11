# Faz 6 taşınabilir restore

## Sonuç

Taşınabilir backup paketini yeni ve boş bir KRCN kullanıcı evine doğrulamalı olarak geri yükleyen akış oluşturuldu.

## Restore kapıları

- Archive ve hedef mutlak yerel path olmalıdır.
- Archive symlink olamaz ve hedefin dışında bulunmalıdır.
- Hedef yok veya tamamen boş olmalıdır; mevcut veri ezilmez.
- Manifest kimliği, archive digest değeri, her payload boyutu ve SHA-256 değeri doğrulanır.
- Bildirilmeyen, duplicate, encrypted, traversal içeren veya secret path taşıyan archive reddedilir.
- Exact dry-run planı ve açık kullanıcı approval olmadan restore uygulanmaz.

## Uygulama davranışı

Payload önce ayrı staging dizinine yazılır ve bütünüyle doğrulanır. Başarılı staging tek işlemle hedef kullanıcı evine alınır. Herhangi bir hata mevcut hedefe kısmi veri bırakmaz.

Kullanıcı policy'leri byte düzeyinde korunur. Dış proje kaynakları restore edilmez; source binding kayıtları `unbound` kalır ve sonuç rebind gereken kaynak sayısını bildirir.

