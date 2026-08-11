# Paket 2 CLI staging baseline

## Amaç

Eski CLI kaynağını takip edilen repository ağacına almadan sabit bir inceleme baseline'ı oluşturmak.

## Uygulama

1. CLI kaynağı salt okunur referanstan yerel ve Git dışındaki staging alanına kopyalandı.
2. Kaynak dosya değiştirilmeden SHA-256 parmak izi, satır sayısı ve byte sayısı kaydedildi.
3. Staging kopyası mevcut import politikasıyla tarandı.
4. Yerel kaynak ve staging yolları kayıtlara alınmadı.

## Baseline

- SHA-256: `311c84facd9cfefaabec7b37d3466947a0063e3ead114dce297009b626ce1e87`
- Satır sayısı: 3.669
- Byte sayısı: 163.852
- Konum sınıfı: yerel ve Git dışı

## Tarama sonucu

Kaynakta uzun tire ve IP adresi içerik sınıfları bulundu. Bu nedenle eski dosya doğrudan repository'ye alınmayacak. Arındırılmış CLI, davranış envanteri temel alınarak modüler ve taşınabilir kod olarak hazırlanacak.

Secret, kullanıcı verisi veya yerel kaynak yolu repository'ye aktarılmadı. Kaynak ve şablon dizinlerinde değişiklik yapılmadı.
