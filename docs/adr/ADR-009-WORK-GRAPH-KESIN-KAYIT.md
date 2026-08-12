# ADR 009: Görev durumu kesin Work Graph kaydından okunur

## Durum

Kabul edildi.

## Karar

Talep, defect, görev, alt görev ve karar yaşam döngüsü proje kapsülündeki revizyonlu JSON kayıtlarında tutulur. Her revizyon append-only olay üretir. SQLite, FTS ve ilerideki vektör katmanları yalnız yeniden üretilebilir projeksiyondur.

Orkestrasyon `task_id` değeri tek bir yürütme kimliğidir ve kalıcı Work Graph kimliğinin yerine geçmez. Yürütme, commit, test, dosya, belge ve release kanıtları açık ilişkilerle kalıcı iş kaydına bağlanır.

## Gerekçe

Görev durumunu vektör benzerliğinden veya geçici ajan oturumundan çıkarmak yanlış devam kararlarına yol açabilir. Revizyon, digest, provenance ve olay geçmişi taşıyan kesin kayıt farklı AI istemcilerinin aynı bağlamı görmesini sağlar.

## Sonuçlar

- `nerede kaldık` yanıtı authoritative Work Graph üzerinden üretilir.
- Tamamlama kanıt gerektirir.
- Bağımlılık döngüleri ve eski planlar reddedilir.
- Arama indeksi silinse bile görev geçmişi kaybolmaz.
- Proje kapsülü görev ve karar geçmişiyle birlikte taşınabilir.
