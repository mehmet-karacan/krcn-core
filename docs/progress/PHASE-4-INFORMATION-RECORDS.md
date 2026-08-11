# Faz 4 provenance ve revision-aware bilgi kayıtları

## Amaç

Retrieval, context ve Memory Gate katmanlarının ortak kullanacağı logical identity, revision, digest, provenance, evidence, ownership ve lifecycle sözleşmesini oluşturmak.

## Uygulanan davranış

1. Altı bilgi sınıfı tek bir versioned information record zarfında temsil edilir.
2. Her kayıt portable logical subject reference ve pozitif revision taşır.
3. Payload canonical SHA-256 digest ile kayda bağlanır.
4. Provenance; kaynak referansı, kaynak revision kimliği, digest ve ilişki türünü içerir.
5. Authoritative source, knowledge, memory, history ve derived kayıtları evidence olmadan kabul edilmez.
6. Bilgi sınıfı ile ownership sınıfı ayrı doğrulanır; secret ve unmanaged ownership bilgi kayıtlarında yasaktır.
7. Secret çağrıştıran alanlar, literal secret örüntüleri ve secret reference değerleri payload içinde reddedilir.
8. Genel özet payload içeriğini göstermez.
9. Knowledge, memory ve derived kayıtlar source revision veya digest değiştiğinde stale olarak tanınır.
10. Authoritative source stale olmaz; yeni revision geldiğinde önceki kayıt superseded edilir.

## Koruma sonucu

Bir bilgi kaydı yalnızca içeriğiyle değil, hangi revision ve kanıttan üretildiğiyle birlikte doğrulanır. Context veya memory katmanı fiziksel makine yolu, secret değeri ya da kaynağı belirsiz bir iddiayı geçerli bilgi gibi taşıyamaz.

## Sonraki adım

Bu kayıt sözleşmesi üzerinde authoritative source ve curated knowledge catalog oluşturulacak; revision çakışması ve stale propagation deterministic hale getirilecek.
