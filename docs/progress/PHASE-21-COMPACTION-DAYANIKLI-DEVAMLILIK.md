# Faz 21 - Compaction dayanıklı devamlılık

## Durum

Tamamlandı.

## Amaç

Model, istemci, oturum veya cihaz değişiminde yeni aktörün tüm geçmişi bağlama
yüklemeden son doğrulanmış konumu bulabilmesi için küçük ve kanıta bağlı bir
devamlılık katmanı eklemek.

## Tamamlananlar

- `ContinuitySnapshot` için 24 KiB yumuşak ve 32 KiB sert sınır uygulandı.
- Eski düşük öncelikli ayrıntılar `omitted_count` ile canonical kayıtlara
  bırakılıyor; güvenli sonraki adımlar sessizce kırpılmıyor.
- Snapshot ile authoritative Work Item revision, orchestration state veya kaynak
  revizyonu çeliştiğinde fail-closed doğrulama eklendi.
- Anlamlı çalışma sonuçları için digest bağlı, append-only `WorkJournalEvent`
  zinciri eklendi.
- Model veya istemci değişiminde kullanılacak, authority ve aktif lease taşımayan
  `FinalizedHandoff` sözleşmesi eklendi.
- Üç kayıt strict şemalara, portable kimliklere, secret ve fiziksel yol
  engellerine bağlandı.
- Repository context yeni normatif spesifikasyon ve üç şemayla güncellendi.

## Doğrulama

- Snapshot round-trip, şema uyumu, boyut kırpma ve authoritative çelişki testleri
  eklendi.
- Journal zincirinde digest değişikliği, sıra, zaman ve Work Item kimliği
  sapmaları doğrulandı.
- Handoff içindeki authority, lease ve tip bozma girişimleri fail-closed test
  edildi.
- Repository, JSON biçimi, context ve tam test paketi doğrulamaları uygulandı.

## Kapsam sınırı

Bu paket yeni bir authoritative durum kaynağı veya workflow engine eklemez.
Kayıtların kalıcı application wiring'i daha sonraki Execution Coordinator
paketinde mevcut ownership ve mutation kapılarıyla compose edilecektir.
Pre-compaction hook yalnız ek güvencedir; temel garanti anlamlı worker adımı
sonunda yazılan checkpoint'tir.

## Sonraki adım

Kanonik `ExecutionTrace` ve tek `StatusProjection` sözleşmesini eklemek.
