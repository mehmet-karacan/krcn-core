# Faz 2 salt okunur onboarding

## Amaç

Bir proje dizinini içeriğini kopyalamadan ve kaynak dizine yazmadan workspace, project ve source binding kayıtlarıyla KRCN Core'a tanıtmak.

## Uygulanan akış

1. Kaynak kökün mutlak, mevcut, normal bir dizin olduğu ve KRCN user-data altında bulunmadığı doğrulanır.
2. Source binding yalnızca `read` ve `metadata` capability'leriyle, `read-only` erişim biçiminde hazırlanır.
3. Project kaydı fiziksel yol yerine source binding kimliğini taşır.
4. Workspace kaydı project kimliğini taşır.
5. Üç kayıt için içerik hash'ine bağlı ayrı mutasyon planları üretilir.
6. Tüm dry-run ve kullanıcı onayları yazma başlamadan doğrulanır.
7. Source binding ve project kayıtları yazılır; workspace referansı en son etkinleştirilir.
8. Genel plan ve sonuç özetlerinde fiziksel locator değeri gösterilmez.

## Koruma sonucu

Onboarding kaynak proje dizininde dosya oluşturmaz, değiştirmez veya silmez. Kayıtlar yalnızca yerel user-data deposuna yazılır. Bu adım sentetik geçici dizinlerle test edildi; canlı proje veya kullanıcı verisi kullanılmadı.

## Sonraki adım

Kaynak ağacını salt okunur tarayan, sembolik bağlantı ve import sınırlarını uygulayan project ve document discovery adapter'ı geliştirilecek.
