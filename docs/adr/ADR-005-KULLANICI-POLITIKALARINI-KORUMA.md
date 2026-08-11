# ADR-005 - Kullanıcı politikalarını koruma

## Durum

Kabul edildi.

## Bağlam

Kullanıcı bir veri tabanında yalnızca `SELECT` çalıştırılmasını, dosyaların silinmemesini veya belirli bir entegrasyonun ağ kullanmamasını isteyebilir. Bu kurallar zaman içinde kullanıcı tarafından açıkça öğretilebilir ve farklı proje veya entegrasyon kapsamlarına bağlanabilir.

Bu tercihlerin core default ayarlarına yazılması güncelleme sırasında ezilme riski oluşturur. Yalnızca konuşma belleğinde tutulması ise başka bir yapay zekâ veya yeni oturum tarafından güvenilir biçimde uygulanmasını engeller.

## Karar

1. Açıkça belirtilen veya kullanıcı tarafından onaylanan kalıcı kurallar user-data sınıfında saklanacak.
2. Kayıtların yeri `.krcn/policies/**` olacak ve Git tarafından taşınan core dosyalarından ayrı tutulacak.
3. Core yalnızca user-policy şemasını, değerlendirme kurallarını ve migration tanımlarını yönetecek.
4. `deny` kararı daha zayıf katmandaki `allow` kararından üstün olacak.
5. Kalıcı bir kısıtlama yalnızca kapsamı gösterilen ve kullanıcı tarafından onaylanan policy değişikliğiyle gevşetilebilecek.
6. Öğrenilmiş fakat onaylanmamış bir tercih aktif policy'ye sessizce dönüştürülmeyecek.
7. Core güncellemesi kullanıcı politikasını değiştirmeden önce dry-run, yedekleme, anlamsal karşılaştırma, doğrulama ve rollback sağlayacak.

## Sonuçlar

- Yeni core sürümleri kullanıcının güvenlik tercihlerini ezemeyecek.
- Codex, Claude, CLI veya başka bir plugin aynı etkili policy sonucunu kullanacak.
- Policy enforcement adapter katmanında uygulanacak ancak kayıt sahipliği core'dan bağımsız kalacak.
- Gerçek policy storage ve değerlendirme motoru sonraki geliştirme adımlarında uygulanacak.
