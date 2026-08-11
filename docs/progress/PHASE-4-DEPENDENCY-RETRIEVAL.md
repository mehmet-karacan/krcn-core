# Faz 4 bağımlılık grafiği ile bilgi getirme

## Amaç

Exact retrieval ile bulunan kayıtları proje, modül, belge, karar, görev ve kaynak ilişkileri üzerinden çevrim dışı ve deterministik biçimde genişletmek.

## İlişki sözleşmesi

1. Her ilişki taşınabilir bir kimlik, başlangıç kaydı, hedef kayıt, ilişki türü, revision, digest, provenance, evidence ve lifecycle taşır.
2. İlişki digest değeri iki uç, ilişki türü ve kanıtın tamamını bağlar.
3. İlişki kanıtı güncel kayıt veya kaynak revision değeriyle eşleşmediğinde kenar `stale` olur.
4. İlişki uçlarından biri eski veya erişilemez olduğunda kenar güncel kabul edilmez.
5. İlişki kayıtları `.krcn/knowledge/relations/**` altında korunmuş kullanıcı verisidir ve yazılmaları açık onay gerektirir.

## Traversal sınırları

Sorgu; başlangıç kayıtlarını, yönü, kabul edilen ilişki türlerini, azami derinliği, düğüm bütçesini ve kenar bütçesini açıkça belirtir. Eski kenarlar ve erişilemeyen düğümler varsayılan olarak izlenmez. Kullanıcı bunları açıkça isterse durum bilgileri korunarak sonuca alınabilir.

Tarama genişlik öncelikli ve kararlı sıralamayla çalışır. Daha önce görülen düğümler yeniden genişletilmez. Yönlü bir döngüye katılan kenarlar döngü olarak işaretlenir ve işlem sonlu kalır. Derinlik veya bütçe sınırına ulaşıldığı sonuçta ayrıca gösterilir.

## Güvenlik sonucu

Dependency retrieval fiziksel source binding konumlarını okumaz, payload içeriğini genel sonuçlara eklemez, provider çağrısı yapmaz ve kullanıcı verisini değiştirmez. Katalog, graph ve sorgu digest değerleri sonucun hangi girdilerden üretildiğini kanıtlar.

## Sonraki adım

Semantic retrieval sözleşmesi oluşturulacak; çevrim dışı deterministik temel davranış korunurken remote embedding veya model erişimi mevcut provider gate arkasında tutulacak.
