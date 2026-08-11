# Faz 6 taşınabilir backup

## Sonuç

Tek KRCN kullanıcı evinden doğrulanabilir ve secret-safe taşınabilir backup üretme akışı oluşturuldu. Backup exact dry-run planı ve açık kullanıcı onayı olmadan yazılmaz.

## Paket içeriği

- User-data, kullanıcı policy'leri, knowledge, memory ve iş kayıtları.
- Runtime state, event, checkpoint ve handoff kayıtları.
- Yeniden üretilebilir derived state.
- Dosya boyutu, SHA-256 ve ownership bilgisi taşıyan manifest.
- Dış kaynaklar için yalnız path içermeyen bağımlılık kaydı.

## Bilinçli dışlamalar

- Dış proje kaynak kodu ve belgeleri.
- Fiziksel source locator değerleri.
- `secrets` ve `.secrets` dizinleri.
- `.env`, private key ve sertifika secret dosyaları.
- Secret taramasına takılan içerik.

Source binding kayıtları backup içinde `unbound` hale getirilir. Mantıksal proje ve binding kimliği korunur; yeni makinede dış proje dizini `project.rebind` ile doğrulanarak bağlanır.

## Güvenlik sonucu

- Backup kullanıcı evinin içine yazılamaz.
- Symlink içeren kullanıcı evi fail-closed davranır.
- Plan sonrasında kullanıcı evi değişirse stale plan uygulanmaz.
- Var olan archive ezilmez.
- Kullanıcı policy dosyaları içerik ve digest değerleriyle aynen korunur.

