# Faz 7 proje metadata çıkarımı

## Sonuç

Kullanıcıdan teknik kimlik istemeden proje adı, project kimliği, workspace kimliği ve source binding kimliği üreten güvenli çıkarım katmanı oluşturuldu.

## Çıkarım sırası

1. `pyproject.toml` içindeki proje adı
2. `package.json` içindeki paket adı
3. `Cargo.toml` içindeki paket adı
4. Proje kökündeki ilk `.csproj` dosyasının adı
5. Proje dizininin adı

## Güvenlik ve taşınabilirlik

- Yalnızca proje kökündeki küçük ve bilinen metadata işaretleri okunur.
- Symlink ve boyut sınırını aşan işaretler kullanılmaz.
- Fiziksel dizin mantıksal kimliğe veya public summary değerine yazılmaz.
- Türkçe proje adları ASCII taşınabilir kimliğe dönüştürülür, görünen ad korunur.
- Kimlik çakışmasında aynı sayısal ek project, workspace ve binding kimliklerine birlikte uygulanır.
- Aynı fiziksel dizini gösteren mevcut source binding bulunursa ikinci kayıt oluşturulmaz.
- Kaynak proje dosyaları değiştirilmez veya kopyalanmaz.
