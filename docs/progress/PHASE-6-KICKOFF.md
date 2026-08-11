# Faz 6 başlangıcı

## Sonuç

Faz 6, Mehmet KARACAN'ın açık onayıyla başlatıldı. Mevcut mimari büyük bir rewrite gerektirmiyor: KRCN kayıtları zaten seçilebilir tek bir `data_root` altında tutuluyor ve proje kaynakları dış dizinden salt okunur bağlanıyor.

## Başlangıç kararı

Faz 6 bu mevcut ayrımı koruyup resmi bir taşınabilir kullanıcı evi, doğrulanmış rebind, güvenli backup, restore ve repo-local migration akışları ekleyecek.

## Korunan alanlar

- Gerçek kullanıcı verisine dokunulmadı.
- Dış proje dosyaları okunmadı, kopyalanmadı veya değiştirilmedi.
- Kullanıcı policy'leri değiştirilmedi.
- Secret değerleri işlenmedi.
- Yalnız ürün çekirdeği belgeleri ve sentetik test sözleşmeleri değiştirildi.

## Kritik recovery sınırı

Tek KRCN kullanıcı evi, KRCN bağlamının tamamını taşıyabilir. Proje kaynakları özellikle kopyalanmadığı için dış proje dizinleri ayrıca korunmalı veya yeni makinede doğrulanarak yeniden bağlanmalıdır.

