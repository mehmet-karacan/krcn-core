# KRCN Core hızlı başlangıç

Bu akış, bir projeyi dosyalarını kopyalamadan KRCN Core'a tam olarak entegre eder ve yerel bilgi aramasını hazırlar.

## 0. İlk entegrasyon veya doğrudan kurulum

KRCN Core repository'sini açan uyumlu bir yapay zekâya bir proje dizini verip `Bu projeyi entegre et` diyebilirsin. Global `krcn` komutu eksikse istemci:

1. İlk entegrasyon isteğini ve proje dizinini bekleyen işlem olarak korur.
2. Platforma uygun kurulum planını gösterir.
3. Kurulum için açık onay alır.
4. CLI'ı kurup doğrular.
5. Aynı proje entegrasyonu isteğine kaldığı yerden devam eder.

Kurulumu doğrudan yapmak istersen Windows, macOS veya Linux üzerinde şu komutları kullan:

Windows:

```powershell
py tools\install_cli.py --plan-only
py tools\install_cli.py
```

macOS ve Linux:

```bash
python3 tools/install_cli.py --plan-only
python3 tools/install_cli.py
```

Yeni bir terminal açıp `krcn doctor` çalıştır. Windows kurulumu kullanıcı ortamını ve PATH değerini yönetir. macOS ve Linux kurulumu ayrı bir yerel Python ortamı oluşturur ve yalnız KRCN tarafından yönetilen shell profile bloğunu ekler. Her iki durumda da kurulum `KRCN_CORE_HOME` ile bu core clone'unu tanır, ancak kullanıcı verisinin yerini belirleyen `KRCN_HOME` değerini değiştirmez. Core güncellendikten sonra aynı kurulum aracını yeniden çalıştır.

## 1. Proje dizininde başla

Terminali entegre etmek istediğin projenin kök dizininde aç. Codex, Claude Code veya repository bağlamını okuyabilen başka bir istemciye doğal dille şunu söyleyebilirsin:

```text
Bu projeyi öğren ve KRCN Core ile entegre et.
```

İstemci `entegre et` niyetini tam `project.integrate` yaşam döngüsüne yönlendirir. Proje kaydı, salt okunur tarama, bilgi çıkarma, rol ve skill seçimi, bilgi vektör indeksi, kaynak kod RAG indeksi ve doğrulama aynı planda tamamlanır. Yalnız bir dizin gerekiyorsa CLI ile de başlayabilirsin:

```bash
krcn project integrate --source <proje-dizini> --scan-mode manual
```

Kayıtlı proje normal çalışmadan önce otomatik güncellik denetiminden geçer:

```bash
krcn project integrate --project <proje-id> --scan-mode automatic
```

Manuel kip her zaman tarar. Otomatik kip, varsayılan 24 saat dolduğunda veya zorunlu bir entegrasyon aşaması eksik olduğunda tarar. Tam ve güncel proje no-op olur. Sonuç hangi kipin ve nedenin kullanıldığını açıkça gösterir.

Kaynak kodla ilgili bir soru için proje dosyalarını baştan sona dolaşmak yerine indeksi sorgula:

```bash
krcn project search-code <proje-id> "kullanıcı silme işlemi nerede yapılıyor"
```

Sonuç göreli dosya yolu, satır aralığı, semboller ve puanlarla birlikte gerçek dosyadan doğrulanmış kod parçasını döndürür. Ham kod SQLite içinde saklanmaz. Ayrı bakım gerektiğinde `krcn project index-code <proje-id>` exact planını kullanabilirsin.

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

Doctor; ortak bağlamı, sahiplik kurallarını, secret taramasını, SQLite FTS5 desteğini, coverage baseline'ını, bilgi indeksini ve proje kaynak kod indekslerinin no-copy bütünlüğünü kontrol eder.

## 4. Bilgi indeksini doğrula veya ayrı olarak oluştur

Tam proje entegrasyonu bilgi kayıtlarını ve hibrit indeksi zaten planlar. Ayrı bakım gerektiğinde önce indeks planını al:

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
