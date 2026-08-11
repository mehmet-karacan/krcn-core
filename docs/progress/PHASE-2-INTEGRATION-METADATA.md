# Faz 2 entegrasyon metadata ve secret reference sınırı

## Amaç

Entegrasyon yapılandırmasını yerel user-data olarak saklarken secret değerlerinin metadata, log, public özet veya Git içine girmesini engellemek.

## Uygulanan sınır

1. Integration kaydı adapter, source binding, durum, configuration, secret reference, policy reference ve revision alanlarını taşır.
2. Configuration içinde password, token, API key, secret, credential veya private key çağrıştıran alan adları reddedilir.
3. Bilinen token, access key, private key, credential assignment ve URL user-info biçimleri configuration değerlerinde reddedilir.
4. Secret değerleri yerine yalnızca `secret://`, `keyring://` veya `env://` reference kabul edilir.
5. Secret reference göreli ve taşınabilir olmalı; parent traversal veya ters eğik çizgi içeremez.
6. Public özet yalnızca configuration alan adlarını ve secret reference adlarını gösterir; değerleri göstermez.
7. Integration kayıtları `.krcn/integrations/**` altında korunan user-data sınıfındadır.
8. Yerel kayıt deposu integration payload'ını yazmadan önce aynı doğrulamayı uygular.

## Doğrulama

Testlerde yalnızca sentetik metadata ve reference kullanıldı. Gerçek credential, bağlantı bilgisi, secret provider veya uzak servis kullanılmadı.

## Sonraki adım

Discovery sonucunu önceki revision ile karşılaştıran ve yalnızca değişen metadata için kontrollü rescan planı üreten akış uygulanacak.
