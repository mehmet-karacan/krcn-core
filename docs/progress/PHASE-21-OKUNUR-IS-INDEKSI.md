# Faz 21 - Okunur iş indeksi

## Durum

Tamamlandı.

## Amaç

Work Graph içindeki kalıcı görev, talep, defect ve karar kayıtlarını sohbet
geçmişine veya modele bağımlı olmadan okunabilen bir `WORK-INDEX.md`
projection'ına dönüştürmek.

## Tamamlananlar

- Proje başına `derived/work/WORK-INDEX.md` konumu tanımlandı.
- Work Graph JSON kayıtlarının otoriter, Markdown dosyasının türetilmiş olduğu
  sözleşmeye bağlandı.
- Aktif ve geçmiş kayıtlar deterministik sıra ve durum sayılarıyla gösterildi.
- Açıklama, kanıt referansı, provenance, kaynak içerik ve fiziksel yolun
  projection'a girmesi engellendi.
- Başlıklar gizli değer ve makine yolu taramasından geçirilip sınırlandı.
- Aktif işler zorunlu tutuldu; geçmiş işler item ve byte bütçesinde
  deterministik kısaltıldı.
- Normal Work Item güncellemesi ve toplu Work Import aynı exact plan içinde
  okunur indeksi güncelliyor.
- Eski veya eksik projection için `work index-readable` servis ve CLI akışı
  eklendi.
- Stale graph, policy, target, yanlış plan, link kaçışı ve eksik authorization
  fail-closed hale getirildi.
- Batch import hatasında okunur index de diğer hedeflerle birlikte rollback
  kapsamına alındı.

## Doğrulama

- Farklı kayıt sırasının aynı Markdown byte'larını ürettiği doğrulandı.
- Secret, mutlak yol, açıklama ve evidence ref değerlerinin çıktıya girmediği
  doğrulandı.
- Aktif kayıtların atılmadığı ve geçmiş kayıt sınırının deterministik olduğu
  doğrulandı.
- Exact plan, stale state, no-op, JSON sözleşmesi, otomatik Work Item ve toplu
  import güncellemesi test edildi.
- CLI varsayılan çıktısının JSON yerine okunur Türkçe özet olduğu doğrulandı.

## Sonraki adım

SQLite kuyruk baseline'ına karşı aday altyapıların uygunluk ölçümünü tamamla ve
sonucu ADR ile sabitle.
