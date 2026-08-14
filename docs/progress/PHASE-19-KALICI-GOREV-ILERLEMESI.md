# Faz 19 - Kalıcı görev ilerlemesi

## Durum

Tamamlandı.

## Tamamlananlar

1. Mevcut TaskPlan, checkpoint, event, handoff ve project resume sınırları incelendi.
2. TaskPlan için strict kalıcı parser eklendi.
3. Proje ve Work Item kapsamında runtime-owned orchestration plan kaydı eklendi.
4. `project.resume` için digest doğrulamalı aktif ilerleme özeti eklendi.
5. On adımlı görev planının sohbet olmadan ilk eksik adıma döndüğü doğrulandı.
6. Her worker tamamlanmasından sonra checkpoint, event, state ve handoff zincirinin ilerlemeyi güncellediği doğrulandı.
7. Tüm iş adımları bittikten sonra bağımsız doğrulama gereksiniminin `verify-task` olarak korunduğu doğrulandı.
8. `project resume` insan tarafından okunabilir tabloda toplam, tamamlanan, mevcut ve sonraki adımı gösteriyor.
9. Aktif runtime kayıtlarının ready kapsülden dışlandığı, tamamlanmış plan kaydının taşınabildiği doğrulandı.
10. Git dışı `.krcn` kullanıcı verisinin ürün JSON sözleşme taramasına karışması engellendi.

## Doğrulama

- 56 odaklı orkestrasyon, proje bağlamı, kapsül, istemci bootstrap ve yerel kayıt testi geçti.
- 31 sözleşme ve ilerleme regresyon testi geçti.
- Tam paket: 819 test geçti, 4 test ortam koşulu nedeniyle atlandı.
- Repository, JSON biçimi, Python derleme, diff ve uzun tire kontrolleri geçti.

## Sonuç

Tek bir görev içindeki çok sayıda madde artık proje ve Work Item kapsamında kalıcı bir plan olarak saklanıyor. Tamamlanan maddeler checkpoint geçmişiyle korunuyor. Yeni bir istemci `project resume` üzerinden mevcut adımı, sıradaki hazır adımı ve bekleyen doğrulamayı öğrenebiliyor. Bu kayıtlar bağlam sağlar, yürütme yetkisi vermez.
