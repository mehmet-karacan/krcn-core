# Faz 21 - Zorunlu kontrol ve baseline kanıtı

## Durum

Tamamlandı.

## Amaç

Güncel HEAD için yayınlanabilirlik kanıtını görünür kılmak. Kalite baseline kayıtları hangi commit üzerinde ölçüldüklerini söylemiyordu; kalite kapısı da hızlı doğrulama ile release matrisini ayırmıyordu.

Otomatik kontrol tetikleyicisi kullanıcı kararıyla kapalı kalmaya devam ediyor. Bu nedenle bu paket, tetikleyici açıldığı anda zorunlu kontrolün hazır olmasını sağlar ve baseline kanıtını tetikleyiciden bağımsız biçimde doğrulanabilir hale getirir.

## Tamamlananlar

1. Hızlı Linux kapısı ayrı bir iş olarak tanımlandı: repository doğrulaması, tam test paketi ve doctor. Bu iş, otomatik doğrulama açıldığında zorunlu kontrol olacak biçimde hazırlandı.
2. Çok platformlu tam matris, offline wheel ve CLI kurulum doğrulamaları ayrı bir işe alındı. Böylece hızlı kapı ile release matrisi birbirinden bağımsız çalışabiliyor.
3. Aynı referans için eş zamanlı koşuları iptal eden concurrency grubu eklendi.
4. Otomatik tetikleyiciler kullanıcı kararıyla kapalı bırakıldı. `push` ve `pull_request` girdileri workflow içinde yorum olarak duruyor; otomatik doğrulama açılacağı zaman yalnız tetikleyici satırları geri alınır, iş yapısı değişmez.
5. Kalite baseline kayıtlarına ölçüm commit'i bağlandı. `.ai/coverage-baseline.json` ve `.ai/cli-baseline.json` artık `source_commit` alanı taşıyor.
6. Baseline attestation modülü eklendi. Eksik veya geçersiz ölçüm commit'i, düşük kapsam değeri ve eski commit üzerinde ölçülmüş baseline durumları makinece raporlanıyor.
7. Doctor kontrol listesine `baseline-attestation` eklendi.
8. `tools/verify_baseline_attestation.py` aracı eklendi ve coverage işine bağlandı. Olağan geliştirme koşusu eskimeyi rapor eder, `--require-current` seçeneği release koşusunda eski baseline'ı hata olarak döndürür.
9. Release kalite kapıları belgesi zorunlu kapı ve baseline attestation kuralıyla güncellendi.

## Doğrulama

- Yeni attestation ve kalite kapısı yapısı testleri ile etkilenen doctor, kalite ve faz testleri geçti.
- Tam test paketi geçti.
- Repository doğrulaması ve JSON biçim kontrolü geçti.
- `verify_baseline_attestation.py --commit <sha>` eski coverage baseline'ını eskimiş olarak raporladı; `--require-current` ile hata döndürdü.

## Baseline tazeleme

Coverage baseline kaydı `50f6e35` commit'inde 466 test ve yüzde 64,01 kapsam ile ölçülmüştü. Ölçüm temiz çalışma ağacında `86065c8` commit'i üzerinde tekrarlandı:

- 855 test çalıştı, 4 test ortam koşulu nedeniyle atlandı, hata yok.
- Ölçülebilir satır: 40231, kapsanan satır: 26915, satır kapsamı yüzde 66,9.
- Süre: 594,9 saniye.

CLI baseline doğrulaması da aynı commit üzerinde tekrarlandı: doctor, offline wheel doğrulaması ve CLI kurulum planı geçti. Her iki baseline artık `86065c8` commit'ine bağlıdır ve `--require-current` kontrolü temiz sonuç veriyor.

## Bu aşamada değiştirilmeyen alanlar

- Test komutları ve mevcut kalite eşikleri.
- Kullanıcı verisi, `.krcn` içeriği ve dış proje kaynakları.
- Release manifest sınırı ve rollback garantileri.

## Geri dönüş

Tetikleyici değişikliği tek dosyada geri alınabilir. Attestation kontrolü additive'dir; alan kaldırıldığında yalnız doctor kontrolü ve araç geri çekilir.

## Sonraki adım

V1 değişmez mimari sözleşmelerinin ADR ile dondurulması.
