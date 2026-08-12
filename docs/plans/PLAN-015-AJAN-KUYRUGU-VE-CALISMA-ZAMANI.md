# Plan 015 - Ajan kuyruğu ve çalışma zamanı

## Durum

Tamamlandı.

## Amaç

Görevleri planner, worker, alt ajan ve verifier rolleri arasında güvenli biçimde çalıştırmak; eş zamanlı işlemlerde veri ve dosya çakışmasını önlemek.

## İş paketleri

1. Kalıcı görev kuyruğu ve görev sahipliği kayıtlarını oluştur.
2. Lease, heartbeat, timeout ve yeniden deneme modelini uygula.
3. Alt ajan görevlerini ana görev ve Work Graph ile ilişkilendir.
4. Proje, görev ve dosya kapsamlı kilitleri tanımla.
5. Checkpoint ve handoff kayıtlarını proje kapsülünde tut.
6. Worker ve verifier yetkilerini ayır.
7. Başarılı tamamlamada test, commit ve indeks güncellemesini tetikle.
8. Başarısız veya yarım kalan iş için güvenli resume üret.

## Kabul ölçütleri

- Aynı görev iki worker tarafından sahiplenilemez.
- Süresi dolan lease güvenli biçimde kurtarılabilir.
- Alt ajan çıktısı kaynak ve doğrulama kanıtıyla ana göreve bağlanır.
- Taşınan kapsülde eski makinenin aktif kilitleri ve lease kayıtları çalışıyor kabul edilmez.
