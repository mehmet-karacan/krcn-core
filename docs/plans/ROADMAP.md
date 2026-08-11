# KRCN Core gelistirme yol haritasi

## Ana hedef

KRCN Core, Git ile dagitilan urun cekirdegini yerel proje ve kullanici verisinden ayiracak. Kullanici yeni surumu cektiginde mevcut projeleri, belgeleri, talepleri, gorevleri, ayarlari ve entegrasyonlari bozulmadan calismaya devam edecek.

Yerel dosyalar varsayilan olarak Git'e veya baska bir uzak servise gonderilmeyecek. Git repository yalnizca core kodunu, surumlenebilir semalari, politikaları, migration tanimlarini, sablonlari ve teknik belgeleri tasiyacak.

## Temel kullanim modeli

Kullanici bir CLI veya yapay zekaya hedefini dogal dille anlatabilecek. Sistem:

1. hedefi ve kabul olcutlerini belirleyecek,
2. ilgili proje, belge, talep ve entegrasyonlari bulacak,
3. gerekli gorev planini uretecek,
4. veri sahipligi ve yetki sinirlarini kontrol edecek,
5. islemi uygulayacak,
6. sonucu dogrulayip Turkce raporlayacak.

## Faz 0 - Mevcut durumu dondur ve tanimla

- Mevcut canli sistem ile baseline adayini karsilastir.
- Calisan komutlari, testleri, semalari ve dizin yapisini kaydet.
- Canli veriyi core, runtime, user-data, derived ve secrets olarak siniflandir.
- Secret, kisisel veri ve kuruma ozel bilgi taramasi yap.
- Aktarilacak ve aktarilmayacak dosyalar icin kullanici onayi al.

Tamamlanma olcutu: Calisan mevcut davranis ve veri sinirlari yeniden uretilebilir bir baseline raporuyla kayit altinda olmali.

## Faz 1 - Repository ve sahiplik temeli

- Urun kaynak kodunu KRCN Core repository yapisina yerlestir.
- `ownership-manifest.yaml` olustur.
- Core, runtime, user-data, derived ve secrets yollarini makinece tanimla.
- Yerel veri dizinlerini `.gitignore` ve dogrulama kurallariyla koru.
- Kurulum, test ve doctor komutlarinin temelini hazirla.

Tamamlanma olcutu: Repository temiz bir bilgisayarda kurulabilmeli ve hicbir canli veri Git'e eklenmemeli.

## Faz 2 - Yerel calisma alani ve entegrasyon modeli

- Proje kimligi ile fiziksel proje yolunu ayir.
- Proje, belge, talep, gorev ve entegrasyon kayit semalarini tanimla.
- Kaynak projeleri varsayilan olarak salt okunur bagla.
- Her entegrasyon icin adapter ve capability sozlesmesi olustur.
- Yerel secret store ve ortam bazli ayarlari tanimla.

Tamamlanma olcutu: Bir proje veya belge kaynagi kopyalanmadan KRCN Core'a tanitilabilmeli.

## Faz 3 - Guvenli `merge into` guncelleme motoru

- `inspect`, `diff`, `merge into`, `verify` ve `rollback` akisini uygula.
- Her surum icin release manifesti ve uyumluluk araligi tanimla.
- Uygulama oncesinde dry-run, yedekleme ve conflict raporu uret.
- Yalniz core tarafindan yonetilen dosyalari guncelle.
- Yerel degisiklikleri ve kullaniciya ait dosyalari koru.
- Sema migrationlarini surumlu ve tekrar calistirilabilir yap.
- Derived veriyi gerektiğinde migrate et veya yeniden olustur.
- Basarisiz dogrulamada otomatik geri donus sagla.

Tamamlanma olcutu: Yeni core surumu mevcut bir kuruluma uygulandiginda projeler, belgeler, talepler ve entegrasyonlar veri kaybi olmadan calismaya devam etmeli.

## Faz 4 - Context, knowledge ve memory

- Authoritative source, knowledge, memory, state, history ve derived data ayrimini uygula.
- Revision-aware kaynak ve indeks modelini kur.
- Exact, semantic ve dependency tabanli retrieval katmanlarini olustur.
- Token butcesi, kanit ve kaynak referanslari tasiyan context paketleri uret.
- Memory Gate ile yalniz uygun ve dogrulanmis bilgiyi kalicilastir.

Tamamlanma olcutu: Ajanlar ayni proje baglamini model veya oturum degisse bile guvenilir bicimde kullanabilmeli.

## Faz 5 - Orchestrator ve dogal dil gorev akisi

- Istegi hedef, plan, capability ve kabul olcutlerine donustur.
- Planner, worker ve verifier sorumluluklarini ayir.
- Ajan, skill, tool ve model registry yapilarini uygula.
- Sonuclari kanit ve dogrulama bilgisiyle kaydet.
- Kritik veya kapsam degistiren kararlarda kullanici onayi iste.

Tamamlanma olcutu: Kullanici yalniz hedefini soylediginde sistem guvenli bir uygulama plani olusturup gorevi sonuca goturebilmeli.

## Faz 6 - Release, kalite ve tasinabilirlik

- CI testleri, baseline regresyonlari ve migration testleri ekle.
- Windows ve macOS kurulum senaryolarini dogrula.
- Release olusturma, paketleme, doctor ve rollback akisini tamamla.
- Temiz kurulum ve mevcut kurulum guncelleme testlerini otomatiklestir.
- Baska bir AI veya gelistirici icin devir ve gelistirme baglamini dogrula.

Tamamlanma olcutu: `clone -> install -> init/onboard -> doctor -> run` ve `pull -> merge into -> verify` akislari belgelenmis ve test edilmis olmali.

## Degismez kabul olcutleri

- Yerel kullanici verisi acik talimat olmadan uzak sisteme gonderilmez.
- Core guncellemesi kullanici verisini silmez veya sessizce degistirmez.
- Her mutasyon oncesinde etki alani gorulebilir.
- Her uygulama geri alinabilir veya yeniden uretilebilir olmalidir.
- Tum kritik sonuclar test, hash, schema veya kaynak referansi ile dogrulanir.
- AI ve CLI calisma sozlesmeleri Ingilizce olabilir; insan operasyon kayitlari Turkce ve ASCII uyumlu yazilir.
- Uzun tire karakterleri kullanilmaz.
