# Faz 22 Olculu Dongu Paketi

## Sonuc

Olculu gece-sabah dongusu icin cekirdek, tasima ve zamanlayicidan bagimsiz bir sozlesme paketi olarak eklendi. Paket yeni yetki uretmez, surec baslatmaz ve surec sonlandirdigini iddia etmez.

## Eklenen kapsam

- Degismez hedef, kisit, kabul referansi ve metrik sahipligi
- Tur, duvar saati, giris tokeni, cikis tokeni, maliyet, deneme ve eszamanlilik butceleri
- Varsayilan olarak sadece okuma, arastirma ve planlama etkileri
- Diger etkiler icin mevcut onay referansi ve yetkilendirme ozeti zorunlulugu
- Calisan ve bagimsiz dogrulayici kimlik ayrimi
- Kanonik JSON ile belirlenmis iterasyon ozet zinciri
- Kabul, geri alma, devam, plato, butce, iptal ve zombie durma nedenleri
- Dogrulanmis kayitlardan devam projeksiyonu
- Kalici fakat yalnizca kayit niteliginde iptal anlami
- CPU, RAM, saglayici kotasi, maliyet, hata ve eszamanlilik baskisina dayali kabul veya erteleme karari
- Aktif isi oldurmeyen ve yalnizca yeni isi kabul eden ya da erteleyen davranis
- Prompt, model ciktisi, fiziksel yol ve secret icermeyen guvenli durum ve sabah ozeti

## Dosyalar

- `src/krcn_core/measured_loop.py`
- `config/measured-loop.json`
- `schemas/measured-loop-policy.schema.json`
- `schemas/measured-loop-plan.schema.json`
- `schemas/measured-loop-iteration.schema.json`
- `schemas/measured-loop-cancellation.schema.json`
- `schemas/measured-loop-status.schema.json`
- `schemas/measured-loop-admission.schema.json`
- `schemas/measured-loop-morning-digest.schema.json`
- `tests/test_measured_loop.py`
- `docs/specifications/MEASURED-LOOP.md`

## Dogrulama kapsamı

Testler su davranislari kapatir:

- Plan ve iterasyon oynama girisimlerinin reddi
- Iterasyon zinciri ve toplam butce denetimi
- Plato, kabul, geri alma, iptal, butce ve zombie durumlari
- Calisan ve dogrulayici kimliklerinin bagimsizligi
- Yalnizca dogrulanmis zincirden devam
- Iptalin surec sinyali veya oldurme iddiasi tasimamasi
- Kaynak baskisinda aktif isi koruyarak yeni isi erteleme
- Plan oncesi, duvar saati sonrasi ve birbiriyle cakisan iterasyon zamanlarinin reddi
- Durum ve devam zamanlarinin son dogrulanmis kayittan geriye gidememesi
- Eski durumla yeni is kabulunun ertelenmesi ve duvar saati biten kosunun butce ile kapanmasi
- Tum kamusal kayitlarin strict JSON Schema dogrulamasi
- Sabah ozetinin hassas icerik tasimamasi

## Entegrasyon siniri

Bu paket uygulama rotalarina, CLI komutlarina, depolama katmanina veya zamanlayiciya baglanmadi. Bu sinir bilincli olarak korunmustur. Sonraki bir entegrasyon paketi mevcut exact-plan, onay, gorev yetkilendirme ve istemci delegasyon kapilarini yeniden kullanmalidir. Mevcut plan veya onay ozetlerinden hicbiri bu kayitlarla genisletilemez.
