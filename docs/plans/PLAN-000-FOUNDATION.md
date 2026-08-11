# PLAN-000 - Repository temelinin kurulması

## Amaç

KRCN Core geliştirmesini, başka bir yapay zekânın veya geliştiricinin bağlam kaybı yaşamadan devralabileceği güvenli bir repository temeline oturtmak.

## Mevcut durum

- GitHub repository yerel çalışma alanına alınmıştır.
- Mevcut canlı sistem ve baseline adayı salt okunur referans kaynakları olarak belirlenmiştir.
- Core, runtime, kullanıcı verisi, türetilmiş veri ve secret sınırları tanımlanmıştır.
- Canlı veya şablon içeriği henüz repository'ye aktarılmamıştır.

## İlk aşama kapsamı

1. Canlı ve şablon dosyalarını sahiplik sınıflarına ayırmak.
2. Secret ve kişisel veri taraması yapmak.
3. Çalışan şablon baseline'ını test sonuçlarıyla doğrulamak.
4. Güvenli repository yapısını ve ownership manifestini hazırlamak.
5. Kullanıcı onayından sonra yalnız uygun core ve belge kaynaklarını aktarmak.

## Kapsam dışı

- Büyük mimari yeniden yazım.
- Canlı kullanıcı verisinin Git'e eklenmesi.
- Context Engine, Orchestrator veya Dependency Engine'in doğrudan uygulanması.
- Canlı sistem üzerinde deploy veya migration.

## Tamamlanma ölçütleri

- Aktarım adayları core/runtime/user-data/derived/secrets olarak sınıflandırılmış olmalı.
- Baseline test komutları ve sonuçları kayıt altına alınmalı.
- Kullanıcı verisini koruyan güncelleme sözleşmesi makinece tanımlanmalı.
- Sonraki uygulama fazı kullanıcı tarafından onaylanmalı.
