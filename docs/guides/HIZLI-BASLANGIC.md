# KRCN Core hızlı başlangıç

Bu akış, bir projeyi dosyalarını kopyalamadan KRCN Core'a tanıtır ve yerel bilgi aramasını hazırlar.

## 1. Proje dizininde başla

Terminali entegre etmek istediğin projenin kök dizininde aç. Codex, Claude Code veya repository bağlamını okuyabilen başka bir istemciye doğal dille şunu söyleyebilirsin:

```text
Bu projeyi öğren ve KRCN Core ile entegre et.
```

İstemci `AGENTS.md`, `AI-CONTEXT.md` ve `.ai/repository-context.json` bağlamını kullanır. Yalnız bir dizin gerekiyorsa CLI ile de başlayabilirsin:

```bash
krcn project learn <proje-dizini>
```

## 2. Yerel çalışma alanını seç

İlk kullanımda önerilen konum `<proje-kökü>/.krcn` olur. İstersen başka bir yerel üst dizin seçebilirsin. Seçilen alan Git'e gönderilmez. Proje kodu, harici belge ve veritabanı dosyası KRCN içine kopyalanmaz.

Önce planı incele, sonra aynı plan kimliğiyle uygula:

```bash
krcn project learn <proje-dizini> --home-choice use-default
krcn project learn <proje-dizini> --home-choice use-default --apply --expected-plan <plan-id> --approval-id <onay-id>
```

## 3. Sağlığı kontrol et

Repository ve aktif yerel alan kontrollerini çalıştır:

```bash
krcn doctor --repo <krcn-core-dizini> --data-root <proje-kökü>/.krcn
```

Doctor; ortak bağlamı, sahiplik kurallarını, secret taramasını, SQLite FTS5 desteğini, coverage baseline'ını ve varsa yerel hibrit indeks bütünlüğünü kontrol eder.

## 4. Bilgi indeksini oluştur

KRCN kataloğuna eklenmiş onaylı bilgi kayıtları varsa önce hibrit indeks planını al:

```bash
krcn knowledge index --repo <krcn-core-dizini> --data-root <proje-kökü>/.krcn
```

Planı uygulamak için dönen kimliği kullan:

```bash
krcn knowledge index --repo <krcn-core-dizini> --data-root <proje-kökü>/.krcn --apply --expected-plan <plan-id>
```

İndeks yalnız `.krcn/derived` alanına yazılır. Silinebilir ve katalogdan tekrar üretilebilir.

## 5. Hibrit arama yap

Sorgu dosyası `schemas/hybrid-retrieval-query.schema.json` sözleşmesine uyar:

```json
{
  "query": {
    "schema_ref": "schemas/hybrid-retrieval-query.schema.json",
    "schema_version": 1,
    "query_id": "ilk-sorgu",
    "text": "veritabanı salt okunur kullanım kuralı",
    "seed_record_ids": [],
    "include_unavailable": false,
    "limit": 10
  }
}
```

```bash
krcn knowledge hybrid --repo <krcn-core-dizini> --data-root <proje-kökü>/.krcn --request-file <sorgu.json>
```

Sonuç exact, FTS, yerel vektör, dependency, authority ve availability puanlarını ayrı gösterir. Ağ veya uzak yapay zekâ provider'ı kullanılmaz.

## 6. Görev durumunu izle

Orchestrator ile yürütülen bir işin durum ve digest doğrulamalı olay sırasını aynı istek bağlamıyla görüntüle:

```bash
krcn orchestrator status --request-file <görev-bağlamı.json>
krcn orchestrator timeline --request-file <görev-bağlamı.json>
```

Zaman çizelgesi olay sırasını ve durum geçişlerini gösterir; görev girdisini, handler payload'ını, secret değerini veya kaynak konumunu açığa çıkarmaz.

## Sorun olduğunda

CLI hata sonrasında `NEXT:` satırında güvenli sonraki işlemi gösterir. Önce bu yönlendirmeyi uygula, ardından `krcn doctor` çalıştır. Kullanıcı policy'si izin vermediği sürece sistem yetki genişletmez; örneğin yalnız `SELECT` öğretilmiş bir veritabanında `DELETE` çalıştırılmaz.
