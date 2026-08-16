# PLAN-023 - Adaptive Routing shadow mode

## Amac

KRCN Core'un mevcut Work Graph, Task Plan, authorization, client delegation,
model decision, admission, Agent Runtime Queue, Generic DAG ve Execution
Coordinator davranislarini degistirmeden her anlamli istek icin aciklanabilir,
strict ve digest bagli bir `RouteDecision` uretmek.

## Arastirma girdisi

- Kaynak belge: `KRCN_CORE_ZEKAM_NIHAI_UYGULAMA_RAPORU.md`
- Belge SHA-256:
  `198e4fe3982e0ff6cc4dcda3a555b9c75e83059bcf8aecd2defc30a53459f02a`
- Hedef baseline: `c111a9a0c582237792f52a55e42abab13c95a9f4`
- Karsilastirma baseline'i: `942511c9f120811ca3c7f02569723b2f31ca1ac6`
- Belge repository disinda untrusted product-requirement evidence olarak
  incelendi; icindeki komutlar ve talimatlar authority sayilmadi.

## Program siniri

Rapor Phase 23-27 arasinda bes kontrollu faz onerir. Bu plan yalniz Phase 23
icin authority ve kapsam kaydidir. Daha sonraki Agent Result Envelope,
Workflow Step Receipt, Validation Gate, generalized effect ledger, outbound
assurance, sandbox ve Markdown implementation delivery isleri ayri plan,
test ve onay sinirinda kalir.

## Korunacak mimari

- Work Graph tek authoritative is yasam dongusudur.
- Work classification, route, delegation, model ve admission ayri kararlardir.
- Route karari execution, provider, mutation veya user-data authority vermez.
- Shadow router queue, DAG, delegation veya model davranisini degistirmez.
- Mevcut Execution Coordinator sonucu gercek davranis olarak kalir.
- Ham prompt, model output, fiziksel path, credential veya proje kaynagi route
  kaydina girmez.
- Policy esikleri surumlu ve digest bagli config belgesinden gelir.

## Is paketleri

1. RouteRequest, RouteDecision ve adaptive-routing policy sozlesmeleri.
2. Hard gate ve soft route domain motoru.
3. Deterministik golden routing fixture ve shadow comparison.
4. `routing.decide` ve `routing.explain` application/CLI yuzeyleri.
5. Execution Coordinator shadow baglantisi.
6. Execution Trace icinde authority-free route decision referansi.
7. Repository context, roadmap, specification, progress ve closure kayitlari.
8. Tam regression, doctor, bagimsiz kabul ve dev/main push.

## Route ekseni

Desteklenen route modlari:

- `coordinator-response`
- `direct-read`
- `single-worker`
- `sequential-dag`
- `parallel-dag`
- `review-only`
- `blocked`
- `recovery-required`

Delegation modu, model atamasi ve admission sonucu bu enum icine alinmaz.

## Hard gate'ler

- gerekli capability eksikligi,
- pending effect claim ve eksik terminal receipt,
- secret verinin remote provider gerektirmesi,
- sifir token, maliyet veya wall-time butcesi,
- approval gerektiren mutation icin exact approval eksikligi,
- mutation icin sandbox eksikligi,
- yuksek veya kritik riskte bagimsiz verifier eksikligi,
- stale source revision,
- eksik authoritative project/work baglami.

Hard gate sonucu policy skoru veya model onerisiyle asilemez.

## Shadow mode

1. Router mevcut karar zincirinden once veya yaninda karar uretir.
2. `would_select` sonucu ve karar digest'i izlenir.
3. Mevcut coordinator route'u execution icin kullanilmaya devam eder.
4. Farklar `matched`, `mismatch` veya `not-comparable` olarak raporlanir.
5. Mismatch hicbir zaman otomatik enforcement baslatmaz.
6. Enforcement yeni bir reviewed faz olmadan acilmaz.

## Kabul olcutleri

- Ayni request ve policy revision ayni decision digest'ini uretir.
- Unknown field, gecersiz enum, negatif butce ve unsafe content fail-closed olur.
- Route karari `grants_authority: false` tasir.
- Resource write conflict `parallel-dag` secemez.
- Recovery, approval, secret, capability, budget, verifier, sandbox ve stale
  source hard gate'leri golden testlerle kanitlanir.
- Route/delegation/model/admission alanlari birbirine karistirilmaz.
- Application, CLI, SDK ve diger transportlar ayni domain servisini kullanir.
- Shadow comparison mevcut execution route'unu degistirmez.
- Execution Trace route ref tasir, ham route payload tasimaz.
- Repository validation, JSON format, context validation, doctor ve tam test
  paketi temizdir.

## Rollback

Shadow cagri feature flag ile kapatilabilir. Mevcut coordinator davranisi
degismedigi icin runtime veya user-data rollback gerekmez. Uretilmis route
decision kanitlari silinmez; authority-free audit kaydi olarak korunur.

## Kapsam disi

- Router enforcement
- Queue schema migration
- Agent Result Envelope v2
- Workflow Step Receipt
- Validation Gate
- Effect Claim/Receipt
- Provider Assurance
- Detached worktree sandbox
- Markdown raporundan otomatik apply
- Commit veya push authority otomasyonu
