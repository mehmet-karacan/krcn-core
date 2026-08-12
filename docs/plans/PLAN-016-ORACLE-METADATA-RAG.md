# Plan 016 - Oracle metadata RAG

## Durum

Tamamlandı.

## Amaç

Oracle veri satırlarını almadan, erişim izni verilen şema tanımlarını, program birimlerini ve bağımlılıkları sürümlü biçimde toplamak, ilişkilendirmek ve aranabilir hale getirmek.

## Kapsam

Veri satırları kapsam dışıdır. Aşağıdaki nesne ve bilgiler kapsam içindedir:

- tablo ve kolonlar;
- primary key, foreign key, unique, check ve not null constraint bilgileri;
- index ve index kolonları;
- sequence;
- view ve materialized view;
- synonym;
- object type ve collection type;
- trigger;
- procedure ve function;
- package specification ve package body;
- grant ve erişim tanımları;
- database link için secret içermeyen tanım metadatası;
- nesneler arası bağımlılıklar;
- erişim izni verilen diğer desteklenen şema nesneleri.

## Toplama ilkesi

Canonical metadata kaynağı Oracle `DBMS_METADATA` API ailesidir. Varsayılan `select-compatible` mod, sabit dictionary sorguları ile `SELECT DBMS_METADATA.GET_DDL`, `GET_DEPENDENT_DDL` ve `GET_GRANTED_DDL` şablonlarını kullanır. `OPEN`, `SET_FILTER`, `ADD_TRANSFORM`, `FETCH_CLOB` ve `CLOSE` akışı yalnız açık `execute` yetkisi ve ayrı session onayıyla kullanılabilir. Kullanıcının `select-only` veya `execute deny` kuralı batch toplama için genişletilemez.

Bağımlılık grafiği yalnızca DDL metin tahminine dayanmaz. Erişilebildiğinde Oracle dependency görünümleri ve mevcut PL/Scope kayıtları kesin kanıt olarak kullanılır. KRCN, metadata toplamak için veritabanı nesnesi oluşturmaz, derleme yapmaz ve session dışı kalıcı ayar değiştirmez.

## İş paketleri

1. Oracle source binding, policy ve secret reference sözleşmesini oluştur.
2. İzin verilen nesne türü allowlist ve şema filtrelerini tanımla.
3. DBMS_METADATA tabanlı ilk tam snapshot adapterini geliştir.
4. Normalize edilmiş DDL, nesne kimliği, içerik hash ve revision modelini oluştur.
5. Artımlı yenilemeyi değişen paketler ve yeni nesneler için uygula.
6. Nesne ve PL/SQL bağımlılık grafiğini kur.
7. Büyük DDL ve package body metinleri için yapısal chunking uygula.
8. Oracle metadata exact, full-text, graph ve vector retrieval katmanlarını oluştur.
9. Yetki eksikliği, unsupported nesne ve bozuk DDL durumlarını raporla.

## Kabul ölçütleri

- Hiçbir tablo satırı veya uygulama verisi KRCN'e alınmaz.
- DDL ve program birimleri nesne türü, owner, ad ve edition bağlamıyla ayrılır.
- Değişmeyen Oracle nesneleri yeniden vektörlenmez.
- Package spec ile package body ayrı sürümlenir ve ilişkilendirilir.
- Kesin bağımlılıklar provenance bilgisiyle saklanır.
- Veritabanı read-only kullanıcı politikası korunur.
