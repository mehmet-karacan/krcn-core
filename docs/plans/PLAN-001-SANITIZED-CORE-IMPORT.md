# PLAN-001 - Sanitize edilmiş core aktarımı

## Durum

Paket 1 kullanıcı onayıyla tamamlandı. Sözleşmeler doğrudan kopyalanmadı; taşınabilir, İngilizce ve makinece doğrulanabilir JSON tanımlarına dönüştürüldü. Launcher dosyaları çalışan CLI giriş noktasından ayrılmadığı için Paket 2'ye bırakıldı.

Sıradaki çalışma Paket 2 - Araçtan bağımsız bağlam ve CLI baseline aşamasıdır.

## Amaç

Mevcut çalışan davranışı koruyarak yalnızca taşınabilir core parçalarını KRCN Core repository yapısına almak. Yerel proje, belge, iş, talep, bellek, bağlantı veya runtime verisi aktarılmayacak.

## Aktarım paketleri

### Paket 1 - Sözleşmeler

- Generic schema tanımları.
- Engine ve policy varsayımları.
- Generic agent registry tanımları.
- Platformdan bağımsız launcher dosyaları.

### Paket 2 - Araçtan bağımsız bağlam ve CLI baseline

- Codex, Claude Code, diğer AI istemcileri ve plugin'ler için ortak context giriş noktası.
- Tek kaynak doğrusuna bağlı ince istemci adaptörleri.
- Aktif planı ve ilerleme durumunu gösteren makinece okunabilir manifest.
- İstemciden bağımsız context resolver.
- Mevcut komut davranışlarının envanteri.
- Monolitik CLI'ın geçici staging kopyası.
- Mutlak yol ve kurulum adı temizliği.
- Otomatik provider keşfinin kaldırılması.
- Runtime ve user-data yazma noktalarının sahiplik kontrolüne bağlanması.

### Paket 3 - Test baseline

- Makineye özel test yollarının kaldırılması.
- Gerçek proje ve bağlantı örneklerinin sentetik fixture ile değiştirilmesi.
- Opsiyonel driver testlerinin capability kontrolüyle ayrılması.
- Ağ erişiminin test sürecinde teknik olarak engellenmesi.

## Aktarım yöntemi

Kaynak dosyalar doğrudan repository'ye kopyalanmayacak. Her paket geçici ve Git dışı staging alanında hazırlanacak. Import taraması temiz geçmeden hiçbir dosya stage edilmeyecek.

## Kabul ölçütleri

- Import taraması bulgu üretmemeli.
- Unit ve hermetic regresyon testleri geçmeli.
- Varsayılan çalışma tamamen offline olmalı.
- Kullanıcı verisi ve yerel metadata Git diff içinde bulunmamalı.
- Core davranışındaki bilinçli değişiklikler ayrı karar kaydıyla açıklanmalı.
- Aktarım diff'i kullanıcı tarafından onaylanmalı.

## Geri dönüş

Aktarım tamamlanana kadar mevcut baseline referansı değiştirilmez. Başarısız veya eksik paket repository'ye alınmaz; staging kopyası silinir ve işlem yeniden başlatılır.
