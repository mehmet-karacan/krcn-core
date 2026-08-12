# ADR 008 - Proje kapsülü yerleşimi

## Durum

Kabul edildi.

## Karar

KRCN kullanıcı verisinin proje kapsamındaki bölümü `projects/<project-id>` altında bağımsız bir kapsül olarak saklanacak. Proje dışı ortak kayıtlar `global`, makineye özel bilgiler `local`, aktif kilitler `locks` ve secret değerleri `secrets` sınırında kalacak.

Kaynak kod indeksi proje kapsülünde tutulacak. Birden fazla projeyi kapsayan derived projeksiyonlar global derived alanında tutulacak.

## Gerekçe

Düz dizin yapısı proje sayısı ve talep, defect, görev, karar, bilgi ve database metadata kayıtları arttığında sahiplik ve taşınabilirlik sınırını belirsizleştiriyor. Proje kapsülü, tek projenin bağlamını bağımsız doğrulamayı, yedeklemeyi ve aktarmayı kolaylaştırıyor.

## Taşınabilirlik kararı

Kapsül proje kaynaklarını içermez. Dışa aktarım fiziksel kaynak yolunu kaldırır ve binding kaydını `unbound` hale getirir. Başka bilgisayarda mevcut proje dizini doğrulanmış rebind ile bağlanır.

Aktif lock, lease ve çalışan ajan sahipliği taşınmaz. Kalıcı görev ve karar geçmişi taşınabilir fakat çalışma zamanı sahipliği yeni makinede yeniden oluşturulur.

## Uyumluluk

Yerleşim v1 salt okunur ve güncelleme uyumluluğuyla desteklenmeye devam eder. V2 geçişi otomatik yapılmaz; backup, exact plan, açık onay, doğrulama ve rollback gerektirir.
