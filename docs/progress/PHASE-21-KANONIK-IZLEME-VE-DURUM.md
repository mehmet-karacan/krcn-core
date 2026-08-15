# Faz 21 - Kanonik izleme ve durum

## Durum

Tamamlandı.

## Amaç

Request, proje, Work Item, plan, context, model, kuyruk, ajan, verifier, kanıt,
süre, token ve tahmini maliyet bilgilerini tek correlation kaydında birleştirmek;
farklı domain statuslarını kullanıcıya tek ve tutarlı durum olarak sunmak.

## Tamamlananlar

- Authority taşımayan, digest bağlı `ExecutionTrace` sözleşmesi eklendi.
- Ham prompt, model çıktısı, kaynak içeriği, secret ve fiziksel yol trace dışında
  bırakıldı.
- Süre, token, cache, retry ve tahmini maliyet alanları strict ve ölçülebilir
  biçimde tanımlandı; bilinmeyen maliyet uydurulmuyor.
- Work Graph, queue, orchestration, research ve derived durumları için tek
  canonical status kümesi ve açık öncelik tablosu eklendi.
- Kullanıcıya ham domain statuslarını vermeyen, yalnız digest ile kanıtlayan
  `StatusProjection` sözleşmesi eklendi.
- Failure, cancellation, blocking, recovery, verification, degraded ve derived
  stale durumlarının öncelikleri fail-closed hale getirildi.
- V1 authority sözleşmesi yeni trace ve projection modülüne bağlandı.
- Repository context normatif spesifikasyon ve iki şemayla güncellendi.

## Doğrulama

- Trace şema round-trip, zaman, token toplamı, maliyet, retry ve digest testleri
  eklendi.
- Secret, fiziksel yol, raw payload işareti, boolean metric ve değiştirilmiş
  aggregate değerler reddedildi.
- Status önceliği, degraded çalışma, derived stale ve bilinmeyen domain durumu
  test edildi.
- Repository context, mimari sözleşme ve JSON biçim doğrulamaları uygulandı.

## Kapsam sınırı

Bu paket mevcut domain durum makinelerini veya event store'ları değiştirmez.
Trace ve status projection yeni bir source of truth değildir. Application ve CLI
wiring'i daha sonraki Execution Coordinator paketinde tek noktadan yapılacaktır.

## Sonraki adım

Proje relocation sınıflandırmasını ve exact source rebind kararlarını
sertleştirmek.
