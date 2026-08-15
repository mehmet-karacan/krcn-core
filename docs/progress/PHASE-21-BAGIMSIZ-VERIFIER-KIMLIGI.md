# Faz 21 - Bağımsız verifier kimliği

## Durum

Tamamlandı.

## Amaç

Generic orchestration akışında worker ve verifier ayrımını yalnız rol etiketiyle
değil, plan ve execution kanıtına bağlı gerçek kimlikle zorunlu kılmak.

## Tamamlananlar

- Worker ve verifier için digest-bound execution identity sözleşmesi eklendi.
- Kimlik task, exact plan, step, rol, actor, session, assignment ve runtime
  türüne bağlandı.
- Handler registry actor digest ve runtime türü için trusted host sınırı oldu.
- İstemcinin kayıtlı handler actor kimliğini request içinden değiştirmesi
  engellendi.
- Verifier actor ve assignment digestlerinin kapsadığı worker'lardan farklı
  olması zorunlu hale getirildi.
- Verifier evidence kayıtları verifier execution identity ID'sine bağlandı.
- Worker checkpoint ve effect journal kayıtları execution identity ID'sini
  taşıyacak şekilde version 2 oldu.
- Tarihsel worker execution version 1 kayıtları okunabilir bırakıldı, ancak yeni
  verified completion için kullanılması engellendi.

## Doğrulama

- Kimlik digest tamper, yanlış rol, yanlış runtime ve locator sızıntısı reddedildi.
- Worker ve verifier handler identity mismatch durumunda callback çalışmadan
  fail-closed davranış doğrulandı.
- Aynı actor veya assignment kullanan worker/verifier çifti reddedildi.
- Kimliksiz legacy worker kaydının bağımsız verification tamamlayamadığı
  doğrulandı.
- Worker replay, checkpoint, service ve Faz 5 entegrasyon testleri yeni kimlikle
  birlikte çalıştırıldı.

## Kapsam sınırı

Execution identity yetki vermez. Mutation, provider, model, database ve proje
onayları mevcut kapılardan geçmeye devam eder. Generic DAG scheduler bir sonraki
pakettir.

## Sonraki adım

Research runtime'daki güvenli scheduler davranışını generic DAG executor olarak
yeniden kullanılabilir hale getirmek.
