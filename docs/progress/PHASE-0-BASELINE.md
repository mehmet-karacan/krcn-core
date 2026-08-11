# Faz 0 baseline inceleme raporu

## Amac

Mevcut canli sistem ile baseline adayini veri kaybi, bilgi sizintisi ve davranis bozulmasi riski olusturmadan incelemek. Bu rapor aktarim karari degildir. Kaynak kod veya yerel veri repository'ye alinmamistir.

## Inceleme yontemi

- Kaynaklar salt okunur olarak tarandi.
- Dosyalar goreli yol ve SHA-256 ile karsilastirildi.
- Core adayi, runtime, user-data, derived, secrets ve gelistirme artifaktlari ayri degerlendirildi.
- Secret ve tasinabilirlik taramasinda degerler raporlanmadi. Yalniz risk kategorileri kullanildi.
- Testler gecici bir kopyada ve ag erisimi teknik olarak engellenmis durumda calistirildi.
- Yerel kaynak konumlari ve ozel proje kimlikleri repository belgelerine yazilmadi.

## Envanter ozeti

| Kaynak sinifi | Dosya sayisi | Yaklasik boyut | Yorum |
|---|---:|---:|---|
| Canli referans | 507 | 698 MB | Isler, proje verisi, indeksler ve runtime durumu iceriyor |
| Mimari ve baseline calisma alani | 119 | 1.77 MB | Tasarim belgeleri ve baseline adayi iceriyor |
| Baseline adayi | 86 | 665 KB | Core, test, ornek proje ve runtime kalintilari birlikte bulunuyor |

Canli referans ile baseline adayi arasindaki ham karsilastirma:

| Durum | Dosya sayisi | Yorum |
|---|---:|---|
| Ayni | 62 | Ortak core, sema, agent, skill ve test dosyalari agirlikta |
| Farkli | 7 | Olay gunlugu, README, proje konumu ve cache farklari |
| Yalniz baseline adayinda | 17 | Test fixture ve cache/runtime kalintilari |
| Yalniz canli referansta | 438 | Buyuk oranda is, proje, runtime ve derived veri |

Core odakli filtrede cache dosyalari disarida birakildiginda 29 dosya canli sistem ile birebir aynidir. Baseline adayina ozel sekiz dosya test fixture kapsamindadir.

## Mevcut calisan yuzey

Baseline surumu `0.1.0-taslak` olarak kayitlidir. CLI su ana gruplari icerir:

- workspace root ve validate;
- project onboard, list ve rescan;
- task list, checkpoint ve kaldigi yer;
- source index build, status ve query;
- memory index ve semantic query;
- database connection metadata ve database index;
- birlesik arama;
- lock yonetimi;
- handoff;
- skill list ve show.

CLI tek bir Python dosyasinda 3.669 satir ve 163.852 byte boyutundadir. Komut ayrıştırma elle yapilmaktadir ve standart bir `--help` yuzeyi yoktur.

## Test sonucu

Testler gecici kopyada calistirildi. Ag cagrilari engellendi.

- Skill yukleme testi: 23 kontrol gecti.
- Regresyon testi: 38 kontrol gecti, 1 kontrol kaldi, 8 opsiyonel kontrol uyarili olarak atlandi.
- Kalan kontrol, gercek bir davranis hatasindan cok testin ortam bagimliligini gosteriyor. Test eksik secret environment degiskenini beklerken CLI once opsiyonel database driver eksikligini bildiriyor.

Regresyon testi hermetic degildir. Is istasyonuna ozel yollar ve belirli kurulum adlari kod icinde sabitlenmistir. Bu test dogrudan aktarilamaz.

## Kritik bulgular

### 1. Yerel veri ile core ayni agacta

Core dosyalari, runtime durumu, olay gunlugu, kullanici tercihleri, proje bellegi, gorevler, indeksler ve baglanti metadata dosyalari ayni kok altinda tutuluyor. Bu durum guvenli update ve release islemini zorlastiriyor.

### 2. Baseline adayi tasinabilir degil

Agent talimatlari, testler, proje metadata dosyalari ve bazi belgeler is istasyonuna ozel mutlak yollar iceriyor. Testlerde belirli proje ve baglanti ornekleri bulunuyor. Bunlar sanitize edilmeden repository'ye alinamaz.

### 3. Varsayilan embedding davranisi yerel veri politikasiyla uyusmuyor

CLI, host makinedeki baska bir arac ayarini otomatik okuyup erisilebilir bir embedding gateway bulursa metin parcalarini uzak servise gonderebiliyor. KRCN Core'da uzak embedding acik ve bilgilendirilmis opt-in olmadan calismamali. Varsayilan davranis offline olmalidir.

### 4. Workspace referanslari kirik

Workspace ayari iki policy dosyasina referans veriyor ancak bu dosyalar baseline adayinda yok. Benzer isimli engine dosyalari mevcut. `validate` yalniz dosya varligi seviyesinde kaldigi icin bu referans sorunu tam olarak yakalanmiyor.

### 5. Testler ortam ve veri bagimli

Testler makineye ozel dizinleri, kayitli projeleri ve opsiyonel Python paketlerini varsayiyor. Core testleri hermetic fixture ile, entegrasyon testleri ise acik capability kosullariyla ayrilmali.

### 6. Secret degeri bulunmadi ancak hassas metadata var

Taramada private key veya GitHub PAT bulunmadi. Database baglanti kayitlari parolayi literal olarak tutmuyor ve secret reference kullaniyor. Buna ragmen host, kullanici, servis, sema, IP, e-posta ve connection metadata hassas kabul edilmeli ve core repository disinda kalmali.

## Aktarim siniflari

### A. Dogrudan aday, yine de inceleme gerekli

- generic schema tanimlari;
- engine ve policy varsayimlari;
- generic agent registry tanimlari;
- platformdan bagimsiz launcher dosyalari;
- generic skill sozlesmeleri.

### B. Donusturulerek alinabilir

- monolitik CLI;
- workspace ayarlari;
- README ve agent talimatlari;
- test runner ve fixture dosyalari;
- model registry ornekleri;
- generic memory sablonlari.

Bu grupta mutlak yollar, yerel kimlikler, otomatik ag davranisi ve canli veri varsayimlari kaldirilmalidir.

### C. Yalniz bilgi kaynagi

- mimari arastirma belgeleri;
- canli sistemden ogrenilen davranislar;
- kullaniciya veya projeye ozel skill ornekleri;
- gecmis karar ve is kayitlari.

Bu bilgiler oldugu gibi kopyalanmaz. Genellestirilmis gereksinim veya test senaryosuna donusturulur.

### D. Repository'ye alinmayacak

- is ve talep dosyalari;
- proje bellegi ve proje metadata kayitlari;
- olay gunlukleri ve checkpoint durumu;
- database baglanti metadata dosyalari;
- SQLite ve vector index dosyalari;
- cache, bytecode ve IDE dosyalari;
- backup ve uretilmis raporlar;
- e-posta, IP, mutlak yol veya kurum bilgisi iceren yerel belgeler;
- secret ve yerel arac ayarlari.

## Sonuc

Mevcut baseline tamamen reddedilmeyecek. Calisan core davranisi korunacak ancak kaynak agac oldugu gibi kopyalanmayacak. Ilk uygulama adimi, ownership manifesti ve offline-first provider politikasini olusturmak; ardindan yalniz onaylanan core dosyalarini sanitize edilmis bir staging alanina almaktir.

## Sonraki onay noktasi

Kullanici onayi sonrasinda Faz 1 su sirayla baslayabilir:

1. ownership manifest semasini tanimlamak;
2. repository dizin yapisini olusturmak;
3. offline-first provider politikasini yazmak;
4. sanitize ve import kontrol listesini makinece dogrulanabilir hale getirmek;
5. onaylanan core adaylarini staging alanina almak;
6. hermetic baseline testlerini yeniden yazmak.
