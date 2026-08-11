# Paket 1 core sözleşmeleri ilerleme kaydı

## Amaç

Mevcut çalışan davranıştan öğrenilen generic sözleşmeleri, yerel veri ve makineye özel metadata taşımadan KRCN Core deposuna almak.

## Uygulanan değişiklikler

1. Workspace, project, task, context, agent ve skill kavramları için JSON Schema sözleşmeleri oluşturuldu.
2. Engine, default policy ve agent kayıtları İngilizce makine sözleşmelerine dönüştürüldü.
3. Varsayılan ağ davranışı `deny` olarak tanımlandı ve uzak servis kullanımı açık onaya bağlandı.
4. Explorer ve verifier rolleri salt okunur, worker rolü kontrollü mutasyon yapabilir olarak tanımlandı.
5. `.ai/**` yolu core sahiplik sınıfına eklendi.
6. Eski sözleşme alanlarının yeni core modeline doğrudan taşınmaması kararlaştırıldı.
7. Launcher dosyaları monolitik CLI bağımlılığı nedeniyle Paket 2'ye ertelendi.

## Doğrulama

- Mevcut 13 temel test geçti.
- Paket 1 için eklenen 9 sözleşme testi geçti.
- Toplam 22 test başarılı oldu.
- Foundation doğrulaması temiz geçti.
- Secret, yerel yol, kişisel metadata ve uzun tire taraması bulgu üretmedi.

## Korunan alanlar

- Yerel projeler ve belgeler aktarılmadı.
- İş, talep, görev, karar ve bellek kayıtları aktarılmadı.
- Runtime olayları, checkpoint'ler ve indeksler aktarılmadı.
- Bağlantı metadata dosyaları ve secret değerleri aktarılmadı.
- Kaynak referans dizinlerinde hiçbir dosya değiştirilmedi.

## Sonraki adım

Paket 2'de mevcut CLI davranışları komut bazında envanterlenecek. CLI geçici alanda ayrıştırılacak; mutlak yollar, otomatik provider keşfi ve sahiplik dışı yazma noktaları temizlenmeden depoya alınmayacak.
