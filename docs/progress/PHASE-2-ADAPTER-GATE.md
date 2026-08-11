# Faz 2 adapter capability ve policy kapısı

## Amaç

CLI, MCP, SDK, plugin veya başka bir istemcinin adapter işlemlerini farklı güvenlik kurallarıyla çalıştırmasını engellemek.

## Uygulanan zincir

1. Adapter desteklediği source türlerini ve işlemleri sürümlü descriptor ile bildirir.
2. Her işlem gerekli capability'leri, varsayılan policy etkisini, mutasyon ve ağ etkisini açıkça tanımlar.
3. Source binding gerekli capability'lerden birini taşımıyorsa işlem hazırlanmaz.
4. Read-only binding mutasyon etkili işlemi yetkilendiremez.
5. Binding içindeki policy reference kayıtlarının tamamı bulunmak zorundadır.
6. Global ve ilgili source, project veya integration kapsamındaki kullanıcı politikaları birlikte değerlendirilir.
7. `deny` işlemi engeller; `require-approval` aynı request kimliğine bağlı onay ister.
8. Request kimliği adapter sürümü, binding revision, capability'ler ve policy revision'larıyla birlikte üretilir.
9. Adapter çalışırken authorization kimliğinin binding ve işlemle eşleştiği tekrar doğrulanır.

## İlk adapter

`local-discovery` adapter'ı yalnızca `read` ve `metadata` capability'leriyle çalışır. Mutasyon veya ağ etkisi bildirmez. Discovery servisi artık ortak adapter authorization olmadan çağrı kabul etmez.

## Sonraki adım

Entegrasyon metadata sözleşmesi oluşturulacak; yalnızca secret reference kabul edilecek ve literal credential değerleri reddedilecek.
