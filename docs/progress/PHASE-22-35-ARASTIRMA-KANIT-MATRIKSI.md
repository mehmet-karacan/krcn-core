# Faz 22 - 35 arastirma kanit matriksi

## Kapsam

`Avenoxai.zip` icindeki 35 gercek Markdown transkripti ayri arastirma
birimleri olarak tamamen incelendi. Paket digest'i
`9f1c9272fbb70f0824672c3a0e14b7ea11840c0714fcdc14f0b439cb74511cd8`
degeridir. macOS metadata kayitlari, `.DS_Store` ve yinelenen 28/29 kanit
agirligi ayri tutuldu. Belgeler talimat degil, untrusted design evidence olarak
degerlendirildi.

## Birim kararlari

| No | Kaynak kimligi | Ana urun karari | Kanit | Oncelik |
|---:|---|---|---|---|
| 1 | `0tMyfqhuB2M` | Bounded loop ve host admission ekle; full access reddet | Orta | P0/P1 |
| 2 | `1hHOgnmAHlE` | Context recall, token ve rehydration etkisini olc | Orta | P1 |
| 3 | `2n84xa99FRY` | Experiment loop ve kontrollu skill yasam dongusu | Orta | P0/P1 |
| 4 | `3inA7z3uk2I` | Mevcut coordinator modelini koru; claim kalitesini olc | Dusuk-orta | P2 |
| 5 | `8TnqjwGnE7c` | Silmeyen memory hygiene ve retention raporu | Dusuk-orta | P1 |
| 6 | `8y6v8k7upuk` | Gorsel tek atim demoyu yeterlilik kaniti sayma | Dusuk | P2 |
| 7 | `9C386jpjnlo` | Gercek proje benchmark runner ve sonuc ekonomisi | Orta | P0 |
| 8 | `a-vO-Re4UqY` | Morning task desk ve memory review; vendor bagimliligi yok | Orta | P1 |
| 9 | `ALq57eCRGF8` | Provider portability drill; politik iddialari urune alma | Dusuk | P2 |
| 10 | `ANsBeSfAkPU` | Long-horizon endurance ve context drift testi | Dusuk-orta | P1 |
| 11 | `aTl3Z5kybvY` | Benchmark execution profile ve karsilastirilabilirlik | Dusuk-orta | P0 |
| 12 | `Bgvie9LtQdk` | Adaptive concurrency, kapasite ve butce backpressure | Dusuk-orta | P1 |
| 13 | `eE7WZ0_LPCU` | Execution evidence zincirini ortak regressions ile guclendir | Orta | P0 |
| 14 | `gVntzdhstis` | Local/remote karari toplam sahiplik maliyetiyle ver | Dusuk-orta | P1 |
| 15 | `INo2BTNzZw0` | JIT context olcumu; kaynak kopyalamama sinirini koru | Orta | P1 |
| 16 | `J7l5txZ3l9s` | Izolasyon regressions ve cache usefulness telemetry | Orta | P0/P1 |
| 17 | `jwWPKjWP4LU` | Marka degil protocol uyumu ve verifier basarisi olc | Dusuk-orta | P1 |
| 18 | `lJAy_ZEHjek` | One-shot completion icin negatif acceptance fixture | Dusuk | P2 |
| 19 | `LxiQ9hzvm_Y` | Project-memory isolation ve adaptive admission | Orta | P0/P1 |
| 20 | `MHk8390TDjw` | Measured loop, plateau, budget, evaluator ve revert | Orta-yuksek | P0 |
| 21 | `MrBB1L0LfkU` | Task contract'a rationale, outcome ve non-goals ekle | Orta | P1 |
| 22 | `Oa4uveD-hHM` | Cost-to-verified-success ile workload routing | Dusuk-orta | P1 |
| 23 | `PaIMHBSMYyE` | Tekrar, varyans ve human correction olcumu | Dusuk-orta | P1 |
| 24 | `pIrrFTvhPVs` | Reward hacking ve evaluator ownership regressions | Ilke orta | P0 |
| 25 | `qccZGsMQs3A` | Donanim piyasa anlatısından core ozelligi cikarma | Dusuk | P2 |
| 26 | `rWE93xcdgC4` | Trial dagilimi ve cost per approved result | Dusuk-orta | P1 |
| 27 | `TREm_35AtB4` | Terminal-run tabanli loop ve skill evaluation | Orta | P0/P1 |
| 28 | `TyG4ylryRfU-a` | Geceyi read/research/plan-only tut; morning digest ekle | Orta | P0 |
| 29 | `TyG4ylryRfU-b` | Duplicate evidence'i tek agirlikla say | Duplicate | P0 |
| 30 | `vZ8dZ773nKA` | Retry, quota ve human intervention dahil gercek maliyet | Dusuk-orta | P1 |
| 31 | `W6H8h0UL1tM` | Unknowns ve plan deviation register | Orta | P1 |
| 32 | `xmMwgggOAmw` | Raw repo zip exportunu reddet; sanitize artifact kullan | Dusuk-orta | P1 |
| 33 | `ygdPDqsGzEY` | Ortamlar arasi ayri promotion plan/approval/verifier | Orta | P0 |
| 34 | `yRBnK-HEK3c` | Long-horizon ve tekrarlı model evaluation | Dusuk-orta | P1 |
| 35 | `z8r237sMmmQ` | Continuous controller, dedupe ve skill governance | Orta-yuksek | P0 |

## Ortak karar

Yeni bir agent framework, temporal graph veya harici memory servisi eklenmeyecek.
Once mevcut dosya, SQLite, Work Graph ve hybrid retrieval katmani asagidaki
olcumlerle tamamlanacaktir:

1. terminal-run tabanli measured loop;
2. exact butce, plateau, cooldown ve cancel;
3. bagimsiz evaluator ve frozen metric ownership;
4. karsilastirilabilir benchmark execution profili;
5. kontrollu skill terfisi;
6. silmeyen memory hygiene ve context effectiveness;
7. evidence dedupe ve ortam promotion kapisi.

Bu matris kaynak transkriptlerin dogru oldugunu iddia etmez. Urun kararlari,
tekrarlanan tasarim ilkeleri ile mevcut KRCN kanitlarinin birlikte
degerlendirilmesidir.

