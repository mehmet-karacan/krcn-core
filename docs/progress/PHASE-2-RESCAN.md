# Faz 2 revision-aware rescan

## Amaç

Yeni discovery sonucunu önceki derived source-state ile karşılaştırmak, gerçek değişiklikleri belirlemek ve yalnızca gerekli metadata güncellemeleri için kontrollü plan üretmek.

## Uygulanan davranış

1. Source-state binding revision, root digest, göreli dosya kanıtları ve keşfedilen teknolojileri taşır.
2. Eklenen, değişen ve kaldırılan dosyalar SHA-256 kanıtlarıyla karşılaştırılır.
3. Eklenen ve kaldırılan teknoloji işaretleri ayrı raporlanır.
4. Kullanıcının elle eklediği project technology kayıtları korunur.
5. Yalnızca `category: discovered` kayıtları güncel discovery sonucuyla yenilenir.
6. Project metadata değişikliği user-data planı üretir ve açık onay gerektirir.
7. Source-state `.krcn/derived/source-states/**` altında derived olarak saklanır ve yalnızca dry-run gerektirir.
8. Tüm authorization kayıtları yazma başlamadan doğrulanır.
9. Project metadata önce, derived source-state en son yazılır.
10. Değişiklik yoksa hiçbir yazma planı üretilmez.

## Koruma sonucu

Rescan kaynak dizine yazmaz. Public plan yalnızca göreli yolları, digest'leri ve sahiplik sınıflarını gösterir. Fiziksel source locator ve dosya içeriği rapora girmez.

## Sonraki adım

Onboarding, list, inspect ve rescan servisleri ortak CLI girişine bağlanacak; aynı servislerin plugin, MCP ve SDK adapter'ları tarafından kullanılacağı sınır tanımlanacak.
