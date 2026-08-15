# ADR 013: V1 değişmez mimari sözleşmeleri

## Durum

Kabul edildi.

## Bağlam

Nihai mimari incelemesi, KRCN Core'un asıl değerinin bileşen sayısı değil, model ve istemci değişse bile yaşayan güvenlik ve kalıcılık omurgası olduğunu tespit etti. Faz 21 boyunca bu omurganın üzerine bileşim, devamlılık, taşınabilirlik ve ölçüm katmanları eklenecektir.

Bu tür bir sadeleştirme çalışmasının bilinen riski, daha akıcı bir kullanıcı deneyimi adına bir güvenlik kapısının sessizce gevşetilmesidir. Belge olarak yazılmış bir ilke, kırıldığında hiçbir şey başarısız olmuyorsa koruma sağlamaz.

## Karar

Aşağıdaki sözleşmeler V1 boyunca değişmezdir. Bileşim, sadeleştirme veya performans çalışması bunları yeniden yorumlayamaz; yalnız wiring, durum sunumu ve API ergonomisi değişebilir.

1. Core, runtime, user-data, derived ve secrets ayrı sahiplik sınıflarıdır.
2. Her create, update, delete veya move etkisi exact plan, dry-run ve açık onay kapısından geçer.
3. Uzak sağlayıcı kullanımı disclosure ve oturum onayı gerektirir; ortamdan sağlayıcı çıkarımı yapılmaz.
4. Work Graph kaydı görev durumu ve geçmişi için authoritative'dir; derived projection onu geçersiz kılamaz.
5. Kaynak kod yerinde okunur; indeks kaynak metnini kalıcı saklamaz ve fiziksel kökü taşımaz.
6. Stale indeks ve digest uyuşmazlığı fail-closed davranır.
7. Kuyruk işlemleri lease, heartbeat ve monotonic fencing kanıtı olmadan tamamlanamaz.
8. Verifier, doğruladığı worker'dan ayrı bir rol ve execution identity taşır; read ve execute dışında yan etki üretmez.
9. Checkpoint, handoff, resume snapshot, trace ve katalog kayıtları bağlam sağlar, execution authority vermez.
10. Model, agent veya delegation kararı yetki kaynağı değildir.
11. Authoritative kullanıcı kaydı JSON'dur; SQLite projection ve vektör indeksleri yeniden üretilebilir.
12. Onaylanmış kullanıcı politikaları kullanıcıya aittir; core güncellemesi şemasını taşıyabilir, anlamını zayıflatamaz.
13. Bir kullanıcı isteğinin gözden geçirilmiş yürütme aşamaları tek immutable root plan altında bağlanır; coordinator policy yetkisini kendi üzerine alamaz.

## Zorlama

Sözleşmeler yalnız bu belgede kalmaz. `config/v1-architecture-contracts.json` her maddeyi mevcut kanıt noktalarına bağlar:

- `module-symbol`: kapının gerçek uygulamasını taşıyan modül ve semboller.
- `policy-flag`: gevşetilmesi durumunda anlamı değişecek policy değeri.
- `policy-members`: korunması gereken sahiplik sınıfları gibi kayıt üyeleri.
- `document-phrase`: normatif spesifikasyon cümlesi.

`tools/verify_architecture_contracts.py` bu bağları çözer, doctor `v1-architecture-contracts` kontrolünü çalıştırır. Bir kapı kaldırılır, bir policy bayrağı ters çevrilir veya normatif cümle silinirse doğrulama başarısız olur.

## Sonuçlar

- Faz 21 bileşim çalışması mevcut servisleri çağırır; policy, authorization ve storage kararlarını sahiplenmez. Bütün kuralları yeniden uygulayan merkezi bir servis bu karara aykırıdır.
- Exact-plan yorgunluğu kapıları kaldırarak değil, ilişkili yan etkileri tek onay zarfında toplayarak azaltılır.
- Yeni bir devamlılık, trace veya katalog kaydı authoritative kayıtların yerine geçemez; yalnız projection olur.
- Bağımsız model bulunamadığında verifier ayrımı execution identity düzeyinde korunur ve degraded durum kullanıcıya gösterilir.
- Kanıt bağı değişen bir refactor, sözleşme kaydını da güncellemek zorundadır; bu güncelleme kararın kendisini değiştirmez.
- Bu sözleşmelerden birini değiştiren bir öneri yeni bir ADR ile gerekçelendirilmelidir.
