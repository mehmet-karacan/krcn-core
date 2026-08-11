# Faz 7 proje öğrenme intent ve dizin çözümleme

## Sonuç

Türkçe ve İngilizce proje öğrenme ifadelerini tek bir `learn-project` intent değerine dönüştüren deterministic çözümleyici oluşturuldu.

## Desteklenen davranış

- Var olan mutlak dizin tek başına verilebilir.
- `öğren`, `tanı`, `tanıt`, `entegre`, `kaydet`, `learn`, `recognize`, `register`, `onboard` ve `integrate` ifadeleri tanınır.
- Boşluk içeren path tırnaklı veya mevcut en uzun dizin prefix değeri olarak çözümlenir.
- Açık istemciler source root değerini ayrı argument olarak iletebilir.

## Fail-closed davranışı

- Olmayan, relative veya symlink dizin reddedilir.
- Birden çok mevcut dizin ambiguity kabul edilir ve işlem durur.
- Tanınmayan eylem proje öğrenmeye çevrilmez.
- Secret benzeri prompt reddedilir.
- Raw prompt ve fiziksel path public summary içinde tutulmaz.

