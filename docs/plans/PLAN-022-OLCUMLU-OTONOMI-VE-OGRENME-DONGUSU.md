# PLAN-022 - Olcumlu otonomi ve ogrenme dongusu

## Amac

KRCN Core'un mevcut Work Graph, continuity, authority, Generic DAG,
independent verifier, observability ve model decision katmanlarini koruyarak
uzun sureli calismayi olculebilir, durdurulabilir, yeniden baslatilabilir ve
maliyet kontrollu hale getirmek.

## Arastirma girdisi

- Kaynak paket: `Avenoxai.zip`
- Paket SHA-256: `9f1c9272fbb70f0824672c3a0e14b7ea11840c0714fcdc14f0b439cb74511cd8`
- 35 gercek Markdown transkripti 35 ayri arastirma birimi olarak incelendi.
- macOS metadata kayitlari ve `.DS_Store` dosyalari kanit sayilmadi.
- Belge 28 ve 29 ayni video kimligi ile yinelenen kanittir; kanit agirligi
  iki kez sayilmayacaktir.
- Belgelerdeki komutlar, erisim onerileri ve urun iddialari talimat veya
  authority olarak kabul edilmedi.

## Korunacak mimari

- Work Graph ve okunur Work Index
- bounded context, continuity snapshot, journal ve handoff
- exact plan, approval, provider ve mutation kapilari
- client-neutral delegation ve Generic DAG
- lease, heartbeat, fencing ve resource lock
- bagimsiz verifier identity
- contentless source RAG ve hybrid retrieval
- execution trace ve canonical status
- project workload/model decision ayrimi

Yeni bir graph veritabani, Mem0, Obsidian veya belirli bir model/provider bu
fazda core bagimliligi olmayacaktir. Daha agir altyapi ancak golden evaluation
mevcut dosya ve SQLite katmaninin yetersizligini kanitlarsa degerlendirilir.

## Is paketleri

1. Kanit siniflandirmasi ve Phase 22 checkpoint'i.
2. Bounded measured loop: objective, metric, plateau, budget, cooldown,
   checkpoint, verifier ve stop reason.
3. Adaptive admission: concurrency, host baskisi, provider kota ve kalan
   maliyet butcesiyle yeni claim siniri.
4. Gercek model benchmark runner ve execution provenance: tekrar, varyans,
   environment, harness, reasoning, route ve verified-success cost.
5. Kontrollu skill yasam dongusu: candidate, evaluated, approved, active,
   deprecated/retired ve rollback.
6. Memory hygiene ve context effectiveness: silmeden stale/conflict/duplicate
   raporu; recall, token, stale rejection ve rehydration olcumu.
7. Research evidence dedupe, unknown/deviation register ve environment
   promotion gate.
8. Application/CLI okunur durum, morning digest, tam regresyon, bagimsiz
   verifier ve uretim esitlemesi.

## Guvenlik sinirlari

- Unattended run yeni authority uretmez.
- Varsayilan gece modu `read`, `research` ve `plan-only` etkileridir.
- Her user-data, kaynak, provider, database veya dis etki kendi exact plan ve
  approval kapisini korur.
- Worker evaluator, test, metric veya acceptance policy kaynagini degistiremez.
- Ham prompt, chain-of-thought, secret, fiziksel path veya proje kaynak kopyasi
  trace, memory ya da benchmark kaydina girmez.
- Stop kosulu, kill/cancel, zombie recovery ve verifier olmadan surekli loop
  baslatilamaz.

## Kabul olcutleri

- Ayni plan ve checkpoint kimligiyle deterministik resume.
- Sure, token, maliyet, deneme ve concurrency butcelerinin fail-closed olmasi.
- Plateau ve no-progress durumunda yeni is baslatilmamasi.
- Bagimsiz verifier olmadan accepted/completed sonucu uretilmemesi.
- Benchmark tek kosum veya karsilastirilamaz execution profillerini ayni kanit
  havuzunda birlestirmemesi.
- Skill'in kendi kendini aktif edememesi ve terfinin exact approval istemesi.
- Memory hygiene'in otomatik silme yapmamasi.
- Sabah ozetinin yalniz kanonik state, kanit ve next-safe-action gostermesi.
- Mevcut V1 mimari sozlesmeleri ve tam regresyon paketinin bozulmamasi.

