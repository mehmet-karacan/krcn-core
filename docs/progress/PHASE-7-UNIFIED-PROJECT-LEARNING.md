# Faz 7 birleşik proje öğrenme planı

## Sonuç

Read-only onboarding ile ilk discovery işlemi tek exact plan altında birleştirildi. Kullanıcı planı bir kez onayladığında source binding, project, workspace ve türetilmiş source state kayıtları birlikte oluşturulabilir.

## Plan içeriği

- Otomatik çıkarılan görünen ad ve taşınabilir kimlikler
- Bulunan dosya sayısı ve teknoloji işaretleri
- Atlanan güvenli olmayan veya sınır dışı kaynakların sayıları
- Oluşturulacak dört kaydın ownership ve approval bilgileri
- Kaynağın salt okunur kalacağı ve kopyalanmayacağı bilgisi

## Güvenlik kanıtı

- Hazırlık işlemi kaynakta ve kullanıcı verisinde mutation yapmaz.
- Fiziksel kaynak dizini public plan özetinde gösterilmez.
- Kaynak içeriği plan ile apply arasında değişirse plan geçersiz olur.
- Bütün kayıtların revision ve authorization bilgileri yazmadan önce doğrulanır.
- User-data kayıtları tek kullanıcı onayını paylaşır, derived state ayrıca kullanıcı onayı istemez.
- Mevcut kullanıcı policy kayıtları okunur ve discovery kararında uygulanır, değiştirilmez.
