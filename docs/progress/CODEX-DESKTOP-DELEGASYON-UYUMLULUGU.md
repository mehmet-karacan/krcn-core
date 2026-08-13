# Codex Desktop Delegasyon Uyumluluğu

## Amaç

Codex Desktop native alt ajan, paralel yürütme ve iptal yeteneklerini sağladığı halde `structured_results=false` bildirimi nedeniyle anlamlı proje işlerinin engellenmesi incelendi ve düzeltildi.

## Kök neden

`structured_results`, native alt ajan sonucunun koordinatöre dönmesi ile makinece doğrulanabilir bir sonuç zarfını aynı kavram olarak ele alıyordu. Native mod gereksinimleri bu bayrağı zorunlu tuttuğu için gerçek bir native sonuç kanalına sahip Codex Desktop `delegation-unavailable` olarak sınıflandırılıyordu.

KRCN içinde `agent-result.schema.json` sözleşmesi bulunmasına rağmen native ajan metnini bu şemaya göre doğrulayan bir runtime adaptörü henüz yoktur. Bu nedenle eski bayrak, uygulanan bir güvenlik garantisi sağlamadan mod seçimini engelliyordu.

## Uygulanan karar

- `native_subagents`, ayrı kimlikli ajan başlatma, lifecycle ve hata durumu ile koordinatöre atfedilmiş terminal metin dönüşü olarak tanımlandı.
- `structured_results`, serbest metin yorumlamadan açık bir sonuç sözleşmesine göre makinece doğrulanabilen payload anlamında korundu.
- `native-parallel`, `native_subagents` ve `parallel_subagents` gerektirir.
- `native-sequential`, `native_subagents` gerektirir.
- `isolated-role-fallback`, native lifecycle kanalı olmadığı için `structured_results` ve `isolated_role_execution` gerektirmeye devam eder.
- Delegasyon zorunluluğu, coordinator-only sınırı, fail-closed davranış ve bütün yetki kapıları değiştirilmedi.

## Canlı Codex doğrulaması

- İki bağımsız denetim alt ajanı eşzamanlı başlatıldı.
- Her iki ajan ayrı görev kimliğiyle mesaj ve nihai metin sonucunu koordinatöre iletti.
- Koordinatör bulguları tek tasarım kararında birleştirdi.
- Kontrollü olarak çıkış kodu 7 üreten alt ajan, başarısız sonucu ayrı ajan kimliğiyle raporladı.
- Çalışan başka bir alt ajan iptal edildi ve durumu `interrupted` olarak gözlendi.
- Bu native metinler koordinasyon girdisidir. Runtime completion, kanıt, lease, fencing, doğrulama, mutasyon ve onay yetkisi sağlamaz.

## Geriye uyumluluk

- Native kanalı olmayan istemciler `delegation-unavailable` kalır.
- Çelişkili veya eksik yetenek bildirimleri reddedilir.
- Isolated ve yapılandırılmamış istemci engellenir.
- Native sequential çalışma görünür biçimde degraded kalır.
- `authority_granted` ve `declaration_grants_authority` değerleri `false` kalır.
- Mevcut profil ve karar şema şekilleri ile mode enumları değişmedi. Yalnız capability policy revision değeri artırıldı.

## Kalan risk

Native terminal metni `agent-result.schema.json` ile doğrulanmaz ve KRCN runtime queue lease veya fencing kimliği taşımaz. Faz 18 runtime köprüsünde session, profile, decision, task, authorization, lease ve verifier bağlarını taşıyan ayrı bir delegated work unit sonucu uygulanmalıdır. Bu eksik, native delegasyonun varlığını engellemez ancak kalıcı completion yetkisinin dışında kalır.
