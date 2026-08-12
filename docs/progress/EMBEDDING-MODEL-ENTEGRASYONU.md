# Embedding model değerlendirmesi ve entegrasyonu

## Sonuç

KRCN Core için Qwen3 Embedding 0.6B birincil, BGE-M3 uzak fallback ve mevcut deterministic hashing çevrimdışı fallback olarak seçildi. İki uzak model de kullanıcının açıkça belirttiği OpenCode provider yapılandırması üzerinden yalnız sentetik metinle çağrıldı ve 1024 boyutlu geçerli vektör döndürdü.

## Değerlendirme

Qwen3 Embedding 0.6B, resmi model kartına göre 100'den fazla dili, programlama dili retrieval kullanımını, 32K bağlamı, instruction kullanımını ve 32 ile 1024 arasında ayarlanabilir boyutu destekliyor. Qwen ekibinin yayımladığı ortak çok dilli MTEB tablosunda genel ve retrieval puanları BGE-M3'ten daha yüksek olduğu için birincil seçildi.

BGE-M3, resmi model kartına göre 100'den fazla dili, 8192 token bağlamını ve dense, sparse ile multi-vector retrieval kiplerini birlikte destekliyor. Qwen3 erişilemez olduğunda güçlü ve farklı özelliklere sahip bir uzak fallback sağlıyor.

Tek sentetik erişim çağrısında Qwen3 yaklaşık 213 ms, BGE-M3 yaklaşık 124 ms yanıt verdi. Bu değerler performans benchmark'ı değildir; yalnız erişim ve yanıt biçimi doğrulamasıdır.

## Tamamlanan işler

1. Sürümlü embedding model kataloğu ve şeması eklendi.
2. Capability registry içine iki model, OpenAI uyumlu adapter ve OpenCode secret provider kayıtları eklendi.
3. API anahtarını kopyalamadan `opencode://` referansını çözen yerel secret provider eklendi.
4. Provider gate onayını ağ çağrısından ve secret çözümlemesinden önce zorunlu kılan adapter eklendi.
5. Yanıt sayısı, sırası, boyutu, sonlu değerleri ve normu doğrulandı.
6. Qwen3, BGE-M3 ve çevrimdışı deterministic hashing sıralaması makine tarafından okunabilir hale getirildi.
7. Proje-local kullanıcı alanına `gpu-fusion-embeddings` entegrasyonu exact plan ve açık onayla kaydedildi.
8. Yeni entegrasyon kaydı üzerinden iki model ayrı ayrı sentetik metinle çağrıldı ve erişilebilirlikleri doğrulandı.

## Doğrulama

- 481 test başarılı oldu, 2 platform testi koşula bağlı olarak atlandı.
- Faz 8 kabul setindeki 72 test başarılı oldu, 1 platform testi koşula bağlı olarak atlandı.
- Satır kapsamı yüzde 63,53 olarak ölçüldü ve yüzde 60 eşiğini geçti.
- Çevrimdışı wheel kurulumu başarılı oldu.
- Repository context, foundation ve JSON biçim kontrolleri başarılı oldu.
- Proje-local `.krcn` altındaki 6 JSON geçerli ve ortak okunabilir biçime uygun bulundu.
- `gpu-fusion` Git çalışma alanı temiz kaldı.
- Sentetik uzak erişim kontrolü iki provider request kimliği içeren exact plan üzerinden uygulandı.

## Sınır

Bu çalışma model seçimi, erişim, fallback ve adapter katmanını tamamlar. `gpu-fusion` knowledge kataloğu henüz boş olduğu için gerçek proje içeriği uzak providera gönderilmedi ve hibrit SQLite indeksine gerçek embedding yazılmadı. Bilgi kayıtları onaylı biçimde oluşturulduktan sonra aynı profil ile belge vektörleri ve sorgu vektörleri üretilmelidir. Bir modelin vektörü diğer modelin vektörüyle karşılaştırılamaz; fallback kullanılırsa indeks aynı profile ait belge vektörlerini içermelidir.

## Kaynaklar

- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- https://github.com/QwenLM/Qwen3-Embedding
- https://huggingface.co/BAAI/bge-m3
- https://github.com/FlagOpen/FlagEmbedding
