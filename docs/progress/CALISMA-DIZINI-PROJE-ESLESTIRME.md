# Çalışma Dizini Proje Eşleştirme

## Durum

İstemciden bağımsız `project.resolve-current` ve `project.resume` operasyonları geliştirildi.

## Tamamlanan davranışlar

- Proje kökü veya alt dizininden kayıtlı source binding otomatik eşleştirilir.
- İç içe proje köklerinde en yakın kayıtlı proje seçilir.
- KRCN Core gibi başka bir dizinden kullanıcı isteğinde geçen proje kimliği veya tam adı eşleştirilir.
- Açık `--project` seçimi diğer çözümleme yollarından önce uygulanır.
- Aynı seviyede birden fazla eşleşme varsa tahmin yapılmaz ve belirsizlik bildirilir.
- Eşleşmeyen dizin güvenli biçimde `matched: false` döndürür.
- Public sonuç fiziksel source locator değerini içermez.
- Resume özeti kayıt durumu, derived source state, bilgi kaydı sayıları ve ilişkili iş handoff özetlerini bir araya getirir.
- Önceki aktif iş yoksa varmış gibi davranılmaz.

## Gerçek veri doğrulaması

- `gpu-fusion` proje kökünden çalışma dizini eşleşmesi yapıldı.
- KRCN Core kökünden proje adı geçen doğal dil isteğiyle eşleşme yapıldı.
- Her iki sonuç aynı proje kaydını ve 1752 dosyalık source state değerini döndürdü.
- İlişkisiz bir dizinde proje eşleşmedi.
- `gpu-fusion` için henüz bilgi kaydı ve aktif orchestration işi bulunmadığı açıkça raporlandı.

## Sonraki adım

Codex, Claude Code ve OpenCode kullanıcı düzeyi başlangıç dosyaları, bu ortak resume operasyonunu çağıran kısa ve yönetilebilir bir KRCN bölümüyle güncellenecektir.
