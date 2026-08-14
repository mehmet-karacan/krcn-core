# Plan 019 - Kalıcı görev ilerlemesi

## Amaç

Tek bir proje görevinin birden fazla adımını sohbetten bağımsız olarak saklamak, her tamamlanan adımda checkpoint üretmek ve yeni istemcinin kalan adımdan güvenli biçimde devam etmesini sağlamak.

## Adımlar

1. Mevcut Work Graph, TaskPlan, checkpoint ve handoff sınırlarını doğrula.
2. TaskPlan kaydını proje ve Work Item kapsamında kalıcı hale getir.
3. Plan kaydını digest, revizyon ve ownership kontrollerine bağla.
4. `project.resume` çıktısına mevcut, tamamlanan ve sonraki adımları ekle.
5. CLI metin çıktısında görev ilerlemesini tablo olarak göster.
6. İstemci bootstrap kurallarını her adım sonrası checkpoint zorunluluğuyla güncelle.
7. On adımlı görev, kesinti, idempotency ve tamper testlerini çalıştır.
8. Repository doğrulamasını tamamla ve ilerleme kaydını kapat.

## Kabul ölçütleri

- Plan sohbet geçmişi olmadan yeniden okunabilir.
- Bir görevdeki tamamlanan adımlar monoton biçimde korunur.
- Yeni model mevcut ve sonraki adımı görebilir.
- Plan veya checkpoint bozulduğunda devam işlemi güvenli biçimde durur.
- Kalıcı plan ve ilerleme kayıtları execution authority sağlamaz.
- Kaynak proje dosyaları ve kullanıcı verileri değiştirilmez.
