# Faz 21 - Zorunlu kontrol ve baseline kanıtı

## Durum

Tamamlandı.

## Amaç

Güncel HEAD için yayınlanabilirlik kanıtını görünür kılmak. Otomatik kontrol tetikleyicisi kapalıyken hiçbir commit için başarılı veya başarısız kontrol kaydı üretilmiyordu; kalite baseline kayıtları da hangi commit üzerinde ölçüldüklerini söylemiyordu.

## Tamamlananlar

1. Zorunlu hızlı Linux kapısı eklendi. Pull request ve geliştirme branch'i push'ları artık repository doğrulaması, tam test paketi ve doctor kontrollerini otomatik çalıştırıyor.
2. Çok platformlu tam matris, offline wheel ve CLI kurulum doğrulamaları istek üzerine ve release etiketlerinde çalışacak biçimde ayrıldı. Otomatik koşuların dakika maliyeti bu ayrımla sınırlı tutuldu.
3. Aynı referans için eş zamanlı koşuları iptal eden concurrency grubu eklendi.
4. Kalite baseline kayıtlarına ölçüm commit'i bağlandı. `.ai/coverage-baseline.json` ve `.ai/cli-baseline.json` artık `source_commit` alanı taşıyor.
5. Baseline attestation modülü eklendi. Eksik veya geçersiz ölçüm commit'i, düşük kapsam değeri ve eski commit üzerinde ölçülmüş baseline durumları makinece raporlanıyor.
6. Doctor kontrol listesine `baseline-attestation` eklendi.
7. `tools/verify_baseline_attestation.py` aracı eklendi ve coverage işine bağlandı. Olağan geliştirme koşusu eskimeyi rapor eder, `--require-current` seçeneği release koşusunda eski baseline'ı hata olarak döndürür.
8. Release kalite kapıları belgesi zorunlu kapı ve baseline attestation kuralıyla güncellendi.

## Doğrulama

- Yeni attestation testleri ve etkilenen doctor, kalite ve faz testleri geçti.
- Tam test paketi geçti.
- Repository doğrulaması ve JSON biçim kontrolü geçti.
- `verify_baseline_attestation.py --commit <sha>` eski coverage baseline'ını eskimiş olarak raporladı; `--require-current` ile hata döndürdü.

## Tespit

Coverage baseline kaydı `50f6e35` commit'inde 466 test ile ölçülmüştü. Güncel HEAD üzerindeki gerçek koşu 838 testtir. Bu fark artık kayıtta görünür ve ölçüm tazelendiğinde `source_commit` ile birlikte güncellenir.

## Bu aşamada değiştirilmeyen alanlar

- Test komutları ve mevcut kalite eşikleri.
- Kullanıcı verisi, `.krcn` içeriği ve dış proje kaynakları.
- Release manifest sınırı ve rollback garantileri.

## Geri dönüş

Tetikleyici değişikliği tek dosyada geri alınabilir. Attestation kontrolü additive'dir; alan kaldırıldığında yalnız doctor kontrolü ve araç geri çekilir.

## Sonraki adım

V1 değişmez mimari sözleşmelerinin ADR ile dondurulması.
