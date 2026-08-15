# Faz 21 - Mimari devamlılık ve taşınabilirlik başlangıcı

## Durum

Devam ediyor.

## Kapsam

Nihai mimari araştırma raporunun uygulama fazıdır. Yeni bir platform veya framework eklenmez. Mevcut Context Builder, Work Graph, kuyruk, verifier, model routing ve araştırma runtime'ı tek yürütme kimliği, tek plan, tek status ve tek trace altında birleştirilir; devamlılık, taşınabilirlik ve ölçüm boşlukları kapatılır.

Plan kaydı: `docs/plans/PLAN-021-MIMARI-DEVAMLILIK-VE-TASINABILIRLIK.md`

## Tamamlananlar

1. Uygulama, `main` üzerinde doğrudan geliştirme yapılmayacak biçimde ayrı bir çalışma kopyası ve `mimari-devamlilik-ve-tasinabilirlik` branch'i üzerine alındı.
2. Branch, doğrulanmış `main` commit'i `2e4d23a` üzerinden oluşturuldu; çalışma ağacı temiz doğrulandı.
3. Rapor baseline commit'i ile branch baseline commit'inin aynı olduğu doğrulandı.
4. Faz 21 planı, kapsam dışı sınırları, iş paketleri ve kabul ölçütleriyle yazıldı.
5. İlerleme kayıtları kataloğu oluşturuldu; geçmiş kayıtlar silinmeden canonical liste altında erişilebilir hale getirildi.
6. `.ai/current-work.json` yalnız aktif fazı, planı ve sınırlı sonraki aksiyonları taşıyacak biçimde sınırlandırıldı.
7. Baseline test ölçümü mevcut HEAD üzerinde çalıştırıldı.

## Doğrulama

- Baseline test koşusu: 838 test geçti, 4 test ortam koşulu nedeniyle atlandı, 955 subtest geçti.
- Süre: 147,7 saniye.
- Ortam: Python 3.14.6, pytest 9.1.1.
- Ölçüm commit'i: `2e4d23a`.
- Testler geçici bir KRCN kullanıcı evi ile çalıştırıldı; gerçek kullanıcı verisi kullanılmadı ve değiştirilmedi.

## Tespit edilen baseline farkı

`.ai/coverage-baseline.json` kaydı 466 test ve `50f6e35` ölçüm commit'ini gösteriyor. Güncel HEAD üzerindeki gerçek koşu 838 testtir. Bu fark, raporun güncel HEAD yayınlanabilirlik kanıtı bulgusunu doğrulamaktadır ve ikinci iş paketinde kaynak commit bağlama ile birlikte giderilecektir.

## Bu aşamada değiştirilmeyen alanlar

- Ürün davranışı, `src/` altındaki kaynak kodu ve mevcut sözleşmeler.
- Kullanıcı verisi, `.krcn` içeriği ve dış proje kaynakları.
- Mevcut ilerleme kayıtlarının içeriği.

## Sonraki adım

Güncel HEAD için zorunlu kontrol tetikleyicisi ve baseline kayıtlarının kaynak commit'e bağlanması.
