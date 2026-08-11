# Faz 4 kanıt ve bütçe kontrollü bağlam paketi

## Amaç

Exact, dependency ve semantic retrieval sonuçlarını; sabit, göreve özgü ve kalıcı bağlam katmanlarıyla birlikte, modelden bağımsız ve deterministik bir context package içinde birleştirmek.

## Katman ve öncelik kuralları

1. `static` katman mimari sınırlar ve zorunlu policy bağlamı içindir.
2. `task` katmanı geçerli göreve doğrudan bağlı içeriktir.
3. `persistent` katman onaylı ve yeniden kullanılabilir bilgidir.
4. Aynı kayıt birden fazla retrieval yolundan gelirse içerik çoğaltılmaz; selection source ve gerekçeleri birleştirilir.
5. Sıralama required durumu, açık priority, layer, authority, retrieval türü, revision ve logical identity üzerinden kararlı biçimde yapılır.

## Bütçe sözleşmesi

Builder UTF-8 byte, Unicode character veya KRCN deterministic token birimiyle çalışabilir. Token birimi, model tokenizer davranışına bağlı değildir; sözcük ve noktalama parçalarının kararlı sayımıdır.

Zorunlu kayıtların tamamı item ve content bütçesine sığmalıdır. Zorunlu içerik sessizce kırpılmaz veya atılmaz. İsteğe bağlı içerik kalan bütçe içinde tam alınır; izin verilmişse Unicode sınırını bozmadan önek olarak kırpılır, aksi halde exclusion kanıtıyla dışarıda bırakılır.

## Kanıt sözleşmesi

Her context item logical source ref, record revision, content digest, information class, ownership, authority rank, layer, selection reason, truncation durumu, projection digest ve provenance evidence taşır. Ayrıca kaydın kendi revision ile digest değerini bağlayan bir record evidence eklenir.

Eski veya erişilemeyen kayıt zorunluysa builder kapalı biçimde hata verir. İsteğe bağlıysa `stale-or-unavailable` gerekçesiyle exclusion listesine alınır. Secret sınırı information record doğrulamasında yeniden uygulanır.

## Uyumluluk

Faz 1'e ait `context-package.schema.json` sürüm 1 korunmuştur. Faz 4 builder yeni `context-package-v2.schema.json` sözleşmesini kullanır; böylece eski motor sözleşmesi sessizce değiştirilmez.

## Sonraki adım

Kalıcı memory için candidate, review, approval, persist, supersede ve revoke durumlarını yöneten Memory Gate oluşturulacak.
