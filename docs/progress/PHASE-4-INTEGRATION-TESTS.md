# Faz 4 bütünleşik testleri

## Amaç

Faz 4 bileşenlerinin yalnızca ayrı birimlerde değil, kalıcı yerel kayıtlar ve ortak application service üzerinden birlikte çalıştığını doğrulamak.

## Geçen senaryolar

1. Aynı kalıcı bilgi kayıtlarından Codex, Claude ve gelecekteki bir model istemcisi için aynı context package yeniden üretildi.
2. İlk servis örneği ve geçici sonuçlar kaldırıldıktan sonra yeni servis örneği aynı context digest değerini sohbet geçmişi olmadan oluşturdu.
3. Kaynak revision değişikliği, ona bağlı knowledge kaydını stale yaptı; kayıt exact retrieval sonucundan ve zorunlu context'ten çıkarıldı.
4. Optional context düşük bütçede deterministic olarak kısaltıldı; zorunlu context bütçeye sığmadığında işlem kapalı biçimde durdu.
5. Açık kullanıcı policy'sindeki database `delete` yasağı, conversation summary kökenli memory review denemesi sırasında değişmedi.
6. Uzak semantic scorer, eşleşen oturum onayı olmadan çağrılmadı; onaydan sonra yalnızca açıkça enjekte edilen scorer çalıştı.
7. Salt okunur retrieval ve context oluşturma sırasında kalıcı yerel kayıtların hash değerleri değişmedi.

## Sınırlar

Testlerin tamamı geçici dizinlerdeki sentetik kaynak, knowledge, policy ve memory adaylarıyla çalıştı. Ağ bağlantısı kurulmadı. Gerçek kullanıcı verisi, canlı kaynak veya yerel referans dizini kullanılmadı.
