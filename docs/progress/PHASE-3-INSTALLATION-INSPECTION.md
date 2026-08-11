# Faz 3 installation inspection

## Amaç

Bir KRCN Core kurulumunun aktif state kaydını, managed core dosyalarını, sahiplik dağılımını ve yarım kalmış deployment durumlarını hiçbir dosyayı değiştirmeden incelemek.

## Uygulanan davranış

1. Installation state katı alan, sürüm, kimlik, hash ve göreli path kurallarıyla doğrulanır.
2. Managed file kayıtları yalnızca `core` sahipliğindeki hedefleri gösterebilir.
3. Her managed dosya stable SHA-256 ve boyut kanıtıyla `verified`, `missing` veya `modified` olarak sınıflandırılır.
4. Runtime, user-data, derived, secrets ve unmanaged dosyalar içerikleri okunmadan sahiplik sayımlarına dahil edilir.
5. Symlink dosya ve dizinleri takip edilmez; sayıları ayrıca raporlanır.
6. Deployment journal içindeki tamamlanmamış durumlar kurulum yolu gösterilmeden raporlanır.
7. Genel sonuç installation root değerini içermez.
8. State bulunmayan kurulum salt okunur biçimde `state_present: false` olarak raporlanabilir.
9. Inspection kimliği state ve gözlenen dosya durumuna bağlı deterministik bir SHA-256 değeridir.
10. Inspection boyunca installation içinde dosya veya dizin oluşturulmaz.

## Koruma sonucu

Secret ve user-data dosyalarının içerikleri inspection amacıyla okunmaz. Yalnızca versioned installation state tarafından managed olarak tanımlanan core dosyaları hashlenir. Fiziksel kurulum yolu public summary içine girmez.

## Sonraki adım

Release manifesti ve payload katı biçimde doğrulanacak; manifest digest güveni ile aktif core sürümünün compatibility aralığı apply öncesinde zorunlu hale getirilecek.
