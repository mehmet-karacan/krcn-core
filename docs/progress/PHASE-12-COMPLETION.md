# Faz 12 Work Graph ve görev ilişkileri tamamlandı

## Sonuç

KRCN Core artık talep, defect, görev, alt görev ve kararları proje kapsülünde kesin Work Graph kayıtları olarak saklar. Görev durumu vektör benzerliğinden veya geçici ajan oturumundan çıkarılmaz.

## Hazırlanan yetenekler

- Revizyonlu ve digest doğrulamalı work item modeli oluşturuldu.
- Her değişiklik için append-only yaşam döngüsü olayı eklendi.
- Bağımlılık, parent, implementasyon, neden, ilişki ve supersede bağları tanımlandı.
- Commit, branch, göreli dosya, test, release ve belge kanıtları eklendi.
- Kanıtsız görev tamamlama reddedildi.
- Eksik hedefli, self-reference içeren ve döngülü ilişkiler reddedildi.
- Eski exact plan uygulaması optimistic revision ve graph digest ile reddedildi.
- Proje bazlı SQLite FTS projeksiyonu atomik ve bütünlük kontrollü üretildi.
- `work.query` ve `work.history` ortak application service ile tüm istemcilere açıldı.
- `project.resume` aktif ve geçmiş görev sayılarını kesin kayıttan göstermeye başladı.

## Taşınabilirlik

Work item ve olay kayıtları `thin` ve `ready` proje kapsüllerinde kullanıcı verisi olarak taşınır. Yeniden üretilebilir SQLite projeksiyonu `thin` pakete girmez. Kaynak kod, mutlak makine yolu, secret ve aktif kilit Work Graph içine alınmaz.

## Korunan sınırlar

- Work Graph kaydı exact plan ve açık onay olmadan değişmez.
- Orkestrasyon yürütme kimliği kalıcı görev kimliği sayılmaz.
- Derived indeks authoritative durum kaynağı değildir.
- Proje kaynak dosyaları kopyalanmaz veya değiştirilmez.
- İnsan görev ve commit kayıtları Türkçe yazılabilir; commit mesajı ASCII kuralı korunur.
