# Faz 7 tamamlandı

## Sonuç

Doğal dille ve yalnızca proje dizinini vererek proje öğrenme deneyimi tamamlandı. Kullanıcı artık workspace, project, binding kimliği veya proje adı üretmek zorunda değildir.

## Tamamlanan yetenekler

- Türkçe ve İngilizce proje öğrenme intent çözümleme.
- Var olan mutlak dizinin tek başına güvenli öğrenme isteği kabul edilmesi.
- Güvenli project marker sırasından görünen ad çıkarımı.
- Türkçe görünen adı koruyan taşınabilir teknik kimlik üretimi.
- Çakışmalarda ortak ve deterministic sayısal ek.
- Aynı fiziksel kaynak için duplicate kayıt engeli.
- Onboarding ile ilk discovery sonucunu birleştiren tek exact plan.
- Tek kullanıcı onayıyla dört yerel kaydın oluşturulması.
- `project.learn`, `krcn project learn` ve `krcn ask` girişleri.
- Codex, Claude, MCP, SDK, plugin ve generic AI için canonical intent route.

## Korunan sınırlar

- Dış proje yerinde ve salt okunur incelenir.
- Proje dosyaları KRCN Core repository'ye veya KRCN kullanıcı evine kopyalanmaz.
- Fiziksel kaynak yolu public plan veya service response içinde gösterilmez.
- User-data kayıtları exact plan ve açık approval olmadan oluşturulmaz.
- Kullanıcının mevcut policy kayıtları değiştirilmez veya zayıflatılmaz.
- Kaynak plan ile apply arasında değişirse eski plan uygulanmaz.
- Gerçek kullanıcı ve referans verileri geliştirme testlerine alınmaz.

## Kullanım

Proje dizini tek başına verilebilir:

```text
krcn project learn <proje-dizini>
```

Doğal dil kullanılabilir:

```text
krcn ask "<proje-dizini> projesini öğren"
```

Bir AI veya plugin bu repository bağlamını okuyorsa aynı isteği `project.learn` operation değerine yönlendirir. İlk çağrı planı gösterir. Kalıcı kayıt için aynı exact plan kimliği ve tek kullanıcı onayı gerekir.

## Bakım durumu

Faz 7 baseline hazırdır. Yeni bir faz veya kapsam genişlemesi Mehmet KARACAN'ın ayrı ve açık onayını gerektirir.
