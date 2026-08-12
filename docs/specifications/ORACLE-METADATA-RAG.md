# Oracle metadata RAG

## Amaç

KRCN Core, Oracle veri satırlarını almadan şema nesnelerini, program birimlerini ve bağımlılıklarını proje kapsülünde sürümlü biçimde saklar. Bu kayıtlar kullanıcı verisidir. SQLite arama indeksi ise yeniden üretilebilir türetilmiş veridir.

## Güven sınırı

- Uygulama tablolarındaki satırlar kapsam dışıdır.
- Serbest SQL kabul edilmez.
- Yalnız sürümlenmiş sorgu şablonları ve bind parametreleri kullanılabilir.
- `select-only` izni yalnız `SELECT` ile çalışan inventory ve `DBMS_METADATA.GET_*` şablonlarına yetki verir.
- `DBMS_METADATA.OPEN`, `SET_FILTER`, `ADD_TRANSFORM`, `FETCH_CLOB` ve `CLOSE` akışı `execute` gerektirir. Kullanıcının `execute deny` kuralı bu akış için değiştirilemez veya yeniden yorumlanamaz.
- Gerçek bağlantı, ayrı network ve provider onayından önce açılamaz.
- Secret değeri, endpoint, wallet yolu ve fiziksel bağlantı bilgisi kalıcı kayda veya Git'e yazılamaz.

## Proje yerleşimi

```text
projects/<project-id>/
  database/oracle/
    snapshots/
    objects/
    revisions/
    dependencies/
    reports/
  derived/retrieval/oracle-metadata-v1.sqlite
```

Snapshot, object, revision, dependency ve report kayıtları yetkili JSON kaynağıdır. SQLite dosyası exact, full-text, vector ve graph sorguları için yeniden kurulabilir projeksiyondur.

## Nesne kimliği ve revizyon

Kimlik; mantıksal database source, container, owner, object type, object name, subobject ve edition alanlarının canonical JSON digest değerinden üretilir. Oracle adları payload içinde değiştirilmeden korunur.

Package specification ve package body ayrı nesne ve revizyondur. Ortak logical group ile ilişkilendirilir. Aynı içerik yeniden gözlendiğinde yeni revizyon oluşturulmaz.

## Toplama modları

### Select-compatible

Varsayılan moddur. Sabit `ALL_*` inventory sorguları ile `SELECT DBMS_METADATA.GET_DDL`, `GET_DEPENDENT_DDL` ve `GET_GRANTED_DDL` şablonlarını kullanır. Mevcut `select-only` politikası korunur.

### Batch open

Yüksek hacimli programatik toplama içindir. Ayrı `oracle-metadata-read` yetkisi, `execute` capability ve exact session onayı gerektirir. Bu koşullardan biri eksikse fail closed davranır.

## Artımlı yenileme

Inventory change token yalnız aday seçmek için kullanılır. İçerik digest değeri revizyonun kesin kanıtıdır. Değişmeyen nesne ve chunk vektörleri yeniden kullanılmalıdır. Yalnız tamamlanmış full snapshot içinde kaybolduğu doğrulanan nesne retired yapılabilir. Partial veya yetki hatalı snapshot mevcut nesneleri retired yapamaz.

## Redaksiyon

Database link raw DDL saklanmaz. Kayıt yalnız mantıksal kimlik, public/private durumu ve credential bulunduğu bilgisi gibi secret içermeyen alanları taşıyabilir. Credential, password, wallet, connect string, host ve service benzeri değerler kalıcılaştırmadan önce redakte edilir.

## Bağımlılıklar

Kesin ilişkiler Oracle dictionary ve varsa önceden üretilmiş PL/Scope kayıtlarından alınır. KRCN bağımlılık toplamak için nesne derlemez ve `ALTER SESSION` çalıştırmaz. Çıkarımsal ilişkiler kesin ilişkilerden ayrı işaretlenir ve provenance bilgisi olmadan yetkili graph sonucu sayılmaz.

## Taşınabilirlik

`thin` kapsül snapshot, object, revision ve dependency JSON kayıtlarını taşıyabilir; derived SQLite indeksini taşımaz. `ready` kapsül yalnız doğrulanmış ve secret içermeyen indeksi taşıyabilir. Fiziksel bağlantı yeniden bağlanmadan refresh yapılamaz.
