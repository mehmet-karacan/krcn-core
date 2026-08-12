# Faz 8 kalite, gözlemlenebilirlik ve kullanıcı deneyimi

## Sonuç

Linux, Windows ve macOS CI matrisi tamamlandı. Dış paket gerektirmeyen Python monitoring tabanlı satır coverage aracı eklendi. İlk baseline ölçümü 462 test üzerinde yüzde `63.99` olarak kaydedildi ve CI alt sınırı yüzde `60` olarak sabitlendi.

Runtime doctor artık SQLite FTS5 ve `query_only` desteğini, coverage baseline'ını, isteğe bağlı aktif kullanıcı evini ve varsa hibrit indeks bütünlüğünü kontrol ediyor. Kontroller salt okunur çalışıyor ve yerel içerik değerlerini rapora taşımıyor.

Orchestrator status yanıtına digest zinciri doğrulanmış okunabilir olay sırası eklendi. Ayrı `orchestrator.timeline` işlemi de aynı zaman çizelgesini CLI, SDK, MCP, plugin ve yapay zekâ istemcilerine ortak sözleşmeyle sunuyor. Olay sırası payload veya secret göstermiyor.

CLI hataları artık yalnız hata metniyle bırakmıyor; plan, approval, project home, secret, eksik kayıt ve indeks durumuna göre güvenli bir `NEXT:` yönlendirmesi veriyor. Uçtan uca başlangıç akışı `docs/guides/HIZLI-BASLANGIC.md` içinde Türkçe olarak belgelendi.

## Düşmanca doğrulamalar

- Bozuk SQLite indeksi runtime doctor tarafından kapalı biçimde reddediliyor.
- FTS kontrol karakterleri sorgu sözdizimi olarak çalıştırılmıyor, güvenli token'lara dönüştürülüyor.
- Aynı düşmanca sorgu deterministik olarak aynı sonucu üretiyor.
- Olay zinciri eksik veya değiştirilmişse zaman çizelgesi oluşturulmuyor.
- Hata yönlendirmesi secret, fiziksel yol veya sorgu sonucu açığa çıkarmıyor.

Bir sonraki ve son adım, tüm Faz 8 davranışlarını temiz kurulum, taşınabilirlik, policy koruma ve istemci eşitliğiyle birlikte doğrulayıp baseline oluşturmaktır.
