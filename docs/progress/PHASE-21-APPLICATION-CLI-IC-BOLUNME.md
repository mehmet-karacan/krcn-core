# Faz 21 - Application ve CLI iç bölünmesi

## Durum

Tamamlandı.

## Amaç

Tek application sözleşmesini ve mevcut istemci davranışını korurken yeni operasyon ekleme yüzeyini küçültmek, dinamik keşif kullanmadan routing ve rendering sorumluluklarını ayırmak.

## Tamamlananlar

1. `ServiceRequest`, `ServiceResponse`, application hatası, operation kataloğu ve ortak argument doğrulamaları `application_contract.py` içine çıkarıldı.
2. `application.py` geriye uyumlu facade olarak bu sözleşmeleri yeniden dışa aktarmaya devam ediyor.
3. Tüm genel operasyonlar `application_registry.py` içindeki explicit operation-to-handler eşlemesine taşındı. Registry eksikliği veya handler yokluğu fail-closed.
4. CLI tablo ve görünüm yardımcıları `cli/renderers/table.py` içine çıkarıldı.
5. Human-readable response seçimi `cli/renderers/service_response.py` içindeki explicit registry'ye taşındı; JSON sözleşmesi değişmedi.
6. Request ve response şemaları operation kataloğuyla birebir eşitlendi. Bu kontrol, response şemasında önceden eksik olan altı model operasyonunu yakaladı ve düzeltti.
7. Dinamik module scanning, permissive fallback ve güvenlik kapısı kopyalama kullanılmadı.

## Korunan sınırlar

- Exact plan ve kullanıcı onayı değişmedi.
- Provider gate değişmedi.
- Ownership ve proje izolasyonu değişmedi.
- Orchestration servis ayrımı değişmedi.
- CLI, SDK, MCP, plugin ve ajan istemcileri aynı ServiceRequest/ServiceResponse sözleşmesini kullanıyor.

## Sonraki adım

Faz 21 kapanış doğrulamasını çalıştırmak, kalıcı çalışma kaydını tamamlandı durumuna almak ve dev `main` HEAD kanıtını yayımlamak.
