# Faz 2 entegrasyon ve koruma testleri

## Amaç

Faz 2 bileşenlerinin tek başına doğru çalışmasının yanında ortak servis üzerinden birlikte çalıştığını ve kullanıcıya ait kaynaklar ile policy kayıtlarını koruduğunu hermetik senaryolarla doğrulamak.

## Doğrulanan akış

1. Temiz ve sentetik bir yerel çalışma alanı oluşturuldu.
2. Aynı application service üzerinden read-only onboarding ve rescan uygulandı.
3. Kaynak dosyalarının içerik hashleri ve değişiklik zamanları işlem öncesi ve sonrası karşılaştırıldı.
4. Kullanıcının veritabanında `delete` işlemini reddeden policy kaydı işlem öncesi ve sonrası byte düzeyinde karşılaştırıldı.
5. CLI, Codex, Claude, MCP, SDK, plugin ve gelecekteki istemci kimliklerinin aynı servis sınırını kullandığı doğrulandı.
6. Fiziksel source ve user-data yollarının genel yanıtlara girmediği doğrulandı.
7. Ağ bağlantısı oluşturma girişimi test ortamında kapatıldı ve tüm akış çevrimdışı tamamlandı.
8. Eksik adapter capability durumunda discovery başlamadan işlem reddedildi.
9. Etkili bir `deny` policy bulunduğunda kaynak okuması başlamadan işlem reddedildi.
10. Literal secret içeren entegrasyon metadata'sı herhangi bir kayıt planı oluşmadan reddedildi.

## Koruma sonucu

Faz 2 akışı kaynak projeye ve kullanıcının açık policy kayıtlarına yazmaz. Derived kayıtlar yeniden üretilebilir alanda, user-data kayıtları ise dry-run, birebir plan kimliği ve açık onay sonrasında tutulur. İstemci seçimi bu kuralları değiştirmez.

## Sonraki adım

Temiz kurulum ve mevcut workspace uyumluluğu doğrulanacak, Faz 2 baseline manifesti oluşturulacak ve Faz 3 `merge into` motoruna geçiş sınırı kaydedilecek.
