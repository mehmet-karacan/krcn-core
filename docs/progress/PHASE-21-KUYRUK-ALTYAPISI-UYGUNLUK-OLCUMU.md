# Faz 21 - Kuyruk altyapısı uygunluk ölçümü

## Durum

Tamamlandı.

## Amaç

Mevcut proje kapsüllü SQLite ajan kuyruğunun V1 kapasitesini ölçmek ve harici
kuyruk servislerine geçiş kararını kanıta bağlamak.

## Tamamlananlar

- Küçük ve orta local-first kapasite profilleri sürümlü politikaya bağlandı.
- Gerçek runtime queue kodunu kullanan ayrı süreçli sentetik ölçüm aracı eklendi.
- Claim gecikmesi, throughput, state retry ve depolama büyüklüğü ölçüldü.
- Lease recovery, stale fencing, integrity ve backup restore kanıtlandı.
- SQLite, Redis Streams, NATS JetStream ve PostgreSQL queue aday matrisi
  oluşturuldu.
- Harici adayların ölçülmediği ve benimsenmediği açıkça kaydedildi.
- SQLite V1 kararı ve yeniden değerlendirme tetikleyicileri ADR ile sabitlendi.

## Ölçüm sonucu

- Küçük profil claim p95: 46.174 ms.
- Orta profil claim p95: 60.361 ms.
- Her iki profil de kendi kabul eşiğini geçti.
- Harici servis eklenmesini gerektiren ölçülmüş bir ihtiyaç bulunmadı.

## Korunan sınırlar

- Canlı proje, kullanıcı verisi ve mevcut runtime kuyruğu değiştirilmedi.
- Ağ çağrısı veya harici servis kurulumu yapılmadı.
- Secret, fiziksel yol ve sağlayıcı bilgisi baseline'a yazılmadı.
- Ölçüm kararı execution veya migration yetkisi üretmiyor.

## Sonraki adım

Execution Coordinator ile mevcut servisleri tek uçtan uca compose edilen akışta
birleştir.
