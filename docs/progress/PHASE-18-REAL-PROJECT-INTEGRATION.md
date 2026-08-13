# Faz 18 gerçek proje entegrasyonu ve görev mirası

## Durum

Tamamlandı.

## Entegre edilen projeler

- `plsql-test-sync`
- `schema-compare-platform`
- `schema-transform-platform`
- `utplsql`
- `sky-microservis`
- `call-center-ui`, fiziksel `sky-ui` projesinin keşfedilen güvenli kimliği

Mevcut `gpu-fusion` kaydı da aynı güncel keşif ve indeks politikalarıyla yeniden doğrulandı. Bütün proje kaynakları yerinde ve salt okunur bağlandı. Kaynak dosyaları KRCN home içine kopyalanmadı ve uzak model sağlayıcısı kullanılmadı.

## Görev mirası

- `schema-compare-platform` için 2 aktif ve 11 tamamlanmış görev aktarıldı.
- `schema-transform-platform` için 18 tamamlanmış görev aktarıldı.
- Görev kimlikleri proje kimliğiyle ad alanına alındı.
- Başlık, açıklama, kabul ölçütü ve kanıt etiketleri Türkçe olarak doğrulandı.
- Her görev doğrulanmış belge veya commit kanıtıyla ilişkilendirildi.
- Yetkili görev kaydı bulunmayan projelerde Git dalı veya commit adına bakılarak aktif görev uydurulmadı.

## Gerçek proje taramasında giderilen sorunlar

- Genel `coverage` dışlaması kaldırıldı. Yalnız gerçek rapor ve geçici coverage çıktıları hedefli olarak dışlanıyor.
- `.pks`, `.pkb`, `.pls`, `.plb`, `.tps` ve `.tpb` uzantıları PL/SQL kaynak kodu olarak indeksleniyor.
- PL/SQL proje yeteneği capability registry içine eklendi.
- Windows junction ve reparse point girdileri kopya kaynak olarak izlenmiyor.
- `.run`, `deploy_log` ve paketlenmiş frontend araç zinciri dizinleri kaynak indeksinden dışlanıyor.
- Resume çıktısındaki `indexed_source_file_count` artık keşfedilen dosya sayısını değil gerçek kaynak kod indeksi sayısını gösteriyor.
- Proje kimliğiyle aynı ada sahip yetkinlik anahtar kelimeleri bilgi kaydında tekilleştiriliyor.

## Doğrulama

- Yedi proje kendi kaynak dizininden doğru proje kimliğiyle çözümleniyor.
- Bütün kaynak kodu SQLite indeksleri bütünlük kontrolünden geçti.
- utPLSQL içindeki 18 gerçek coverage PL/SQL kaynağı indekste yer alıyor.
- 31 görev kaydının Türkçe metin ve kanıt alanları doğrulandı.
- JSON biçim denetimi 185 belgeyi değişiklik gerektirmeden doğruladı.
- Tam test paketi 668 testte geçti, 2 platforma bağlı test atlandı.

## Sonraki adım

Proje özel benchmark çalıştırıcısı, uzmanlık bazlı model puanlama ve birincil/yedek model ataması tamamlanacak. Ardından delegated work unit, kalıcı runtime köprüsü ve coordinator politikası `gpu-fusion` pilotunda uçtan uca doğrulanacak.
