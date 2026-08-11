# Faz 2 başlangıç kaydı

## Başlangıç baseline'ı

Faz 2, tamamlanmış Faz 1 CLI ve güvenlik baseline'ı üzerinden başlatıldı. Başlangıç commit'i `4a6981d` olarak kaydedildi.

## İlk çalışma sınırı

İlk uygulama yalnızca sentetik kaynaklarla yapılacak. Yerel workspace ve source binding kayıt deposu hazırlanacak; ardından kaynak dizine yazmayan salt okunur proje onboarding akışı uygulanacak.

Canlı ve şablon referans kaynakları bu aşamada okunmayacak veya değiştirilmeyecek. Kullanıcı verisi migration'ı, gerçek veri tabanı bağlantısı ve uzak provider kullanımı kapsam dışıdır.

## Güvenlik bağımlılıkları

Faz 2 adapter'ları aşağıdaki Faz 1 kapılarını ortak kullanacak:

- source binding doğrulaması;
- kullanıcı policy değerlendirmesi;
- veri tabanı statement koruması;
- sahiplik, dry-run ve onay mutasyon kapısı;
- offline provider ve oturum onayı kapısı.

## Sonraki adım

Workspace, project ve source binding kayıtları için atomic, revision-aware ve yerel user-data deposu uygulanacak.
