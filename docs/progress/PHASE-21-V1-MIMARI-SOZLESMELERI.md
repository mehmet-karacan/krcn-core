# Faz 21 - V1 değişmez mimari sözleşmeleri

## Durum

Tamamlandı.

## Amaç

Bileşim ve sadeleştirme paketleri başlamadan önce dokunulmayacak güvenlik ve kalıcılık sözleşmelerini dondurmak. Yalnız belge olarak yazılmış bir ilke, kırıldığında hiçbir doğrulama başarısız olmuyorsa koruma sağlamaz; bu nedenle karar makinece çözülebilir kanıtlara bağlandı.

## Tamamlananlar

1. `ADR-013` yazıldı ve 13 değişmez sözleşme kabul edildi: sahiplik sınıfları, exact plan ve onay, sağlayıcı disclosure, Work Graph authority, kaynağı yerinde okuma, stale fail-closed, lease ve fencing, bağımsız verifier, kayıtların yetki vermemesi, model kararının yetki olmaması, tek immutable root execution, JSON authoritative ve yeniden üretilebilir projection, kullanıcı politikalarının korunması. Golden retrieval değerlendirmesi bu sözleşmeleri gevşetmez ve yetki üretmez.
2. `config/v1-architecture-contracts.json` eklendi. Her sözleşme modül sembolü, policy değeri, policy üyesi veya normatif spesifikasyon cümlesi olarak kanıt noktalarına bağlandı.
3. `schemas/v1-architecture-contracts.schema.json` ile kayıt biçimi sabitlendi.
4. `src/krcn_core/architecture_contracts.py` kanıt çözümlemesini uyguladı. Modül import edilebilir mi, sembol var mı, policy değeri beklenen mi, normatif cümle yerinde mi kontrol ediliyor.
5. `tools/verify_architecture_contracts.py` aracı eklendi; metin ve JSON çıktısı veriyor.
6. Doctor kontrol listesine `v1-architecture-contracts` eklendi.
7. Her sözleşmenin en az bir çalıştırılabilir bağ taşıması test ile zorunlu kılındı.

## Doğrulama

- 15 sözleşme testi geçti.
- Repository üzerinde 13 sözleşmenin tamamı çözüldü.
- Negatif senaryolar doğrulandı: `stale_index_allowed` değerini gevşetmek, `secrets` sahiplik sınıfını kaldırmak, model routing normatif cümlesini silmek, `implicit_provider_discovery` değerini açmak ve karar kaydını silmek ilgili sözleşmeyi başarısız yapıyor.
- Tam test paketi, repository doğrulaması ve JSON biçim kontrolü geçti.

## Kapsam sınırı

Bu paket ürün davranışını değiştirmez. Mevcut kapılar aynen çalışmaya devam eder; eklenen tek şey bu kapıların varlığını ve anlamını doğrulayan bir kontrol katmanıdır.

Kanıt bağı değişen bir refactor sözleşme kaydını da güncellemek zorundadır. Bu güncelleme kararın kendisini değiştirmez; sözleşme metnini değiştirmek yeni bir ADR gerektirir.

## Sonraki adım

Sınırlı devamlılık snapshot'ı, append-only çalışma günlüğü ve yetki taşımayan devir kaydı sözleşmeleri.
