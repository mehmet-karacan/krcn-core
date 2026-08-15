# Faz 21 - Generic DAG executor

## Durum

Tamamlandı.

## Amaç

Research runtime içinde çalışan DAG, lease, heartbeat ve paralellik davranışını
TaskPlan tabanlı bütün generic orchestration akışlarında yeniden kullanılabilir
hale getirmek.

## Tamamlananlar

- TaskPlan ve TaskAuthorization ile exact bağlı generic execution planı eklendi.
- Her executable step için handler, execution identity ve logical resource
  assignment zorunlu hale getirildi.
- Planner adımlarının runtime queue'ya girmesi engellendi.
- Queue kontrol işlemleri seri, gerçek handler çalışmaları bounded parallel hale
  getirildi.
- Hazır step seçimi bağımlılık completion kanıtına bağlandı.
- Çakışan project, task ve path resource refleri aynı paralel batch'ten çıkarıldı.
- Plan ve step özel claim capability ile yanlış queue item lease edilmesi önlendi.
- Her lease için ilk ve periyodik heartbeat, owner digest ve fencing kanıtı
  zorunlu tutuldu.
- Completed step tekrar çalıştırılmadan partial DAG resume desteği eklendi.
- Read-only hata retry edilebilir, execute/write/network hataları fail-closed
  recovery sınırında bırakıldı.
- Adapter sonucu task, plan, step ve execution identity digestlerine bağlandı.

## Doğrulama

- İki bağımsız root step'in gerçek zamanda paralel çalıştığı barrier ile
  doğrulandı.
- Aynı logical resource kullanan root step'lerin seri çalıştığı doğrulandı.
- Bir root tamamlanıp diğeri kesildiğinde yeni exact planın tamamlanan root'u
  tekrar çalıştırmadan devam ettiği doğrulandı.
- Stale queue, yanlış exact plan, verifier identity reuse, adapter actor mismatch
  ve result tamper fail-closed test edildi.
- Public plan ve result sözleşmeleri JSON şemalarıyla doğrulandı.

## Kapsam sınırı

Bu paket scheduler ve runtime checkpoint katmanıdır. Domain worker/verifier
handlerlarını tek uçtan uca akışta compose etme sorumluluğu Execution
Coordinator paketindedir.

## Sonraki adım

Work Graph kayıtlarından okunur ve yeniden üretilebilir WORK-INDEX projection
oluşturmak.
