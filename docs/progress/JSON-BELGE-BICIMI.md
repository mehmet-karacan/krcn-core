# JSON belge biçimi bakım çalışması

## Sonuç

KRCN Core deposundaki sürümlü JSON dosyaları ve KRCN tarafından üretilen kalıcı JSON belgeleri ortak, okunabilir bir biçime bağlandı. Hash ve exact-plan kimlikleri için kullanılan kompakt kanonik temsil dosya yazımından ayrıldı.

## Tamamlanan işler

1. Ortak JSON parse, kanonik kimlik ve okunabilir belge yazım katmanı eklendi.
2. Repository JSON dosyaları iki boşluk girintili UTF-8 biçimine getirildi.
3. Repository doğrulamasına JSON sözdizimi ve biçim kapısı eklendi.
4. Yerel kayıtlar, proje evi manifestleri, migration çıktıları, türetilmiş çıktılar, deployment belgeleri ve portable backup JSON belgeleri okunabilir yazıma geçirildi.
5. Eski kompakt kullanıcı kayıtlarının okunabilirliği korundu.
6. JSON biçim değişikliğinin payload hash, policy, source revision ve exact-plan bütünlüğünü değiştirmediği hedefli testlerle doğrulandı.

## Kullanım

Sürümlü JSON dosyalarını düzenlemek için:

```text
python tools/format_json.py
```

Yalnız doğrulamak için:

```text
python tools/format_json.py --check
```

Bu araç yalnız Git tarafından izlenen repository JSON dosyalarını düzenler. Yerel `.krcn` kullanıcı verisini izinsiz değiştirmez.

## Doğrulama

- 123 sürümlü JSON belgesi biçim denetiminden geçti.
- Toplu biçim değişikliğinde yalnızca iki bağlam belgesine planlanan yeni alanlar eklendi; diğer JSON değerleri birebir korundu.
- 473 test başarılı oldu, 2 platform testi koşula bağlı olarak atlandı.
- Faz 8 kabul setindeki 72 test başarılı oldu, 1 platform testi koşula bağlı olarak atlandı.
- Satır kapsamı yüzde 63,91 olarak ölçüldü ve yüzde 60 eşiğini geçti.
- Çevrimdışı wheel kurulumu ve proje öğrenme doğrulaması başarılı oldu.
- `gpu-fusion` proje evindeki 5 JSON ile önceki merkezi alandaki 4 JSON, değerleri korunarak aynı biçime getirildi ve iki veri kökünde de doctor denetimi geçti.
