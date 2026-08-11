# PLAN-000 - Repository temelinin kurulması

## Amaç

KRCN Core geliştirmesini, başka bir yapay zekânın veya geliştiricinin bağlam kaybı yaşamadan devralabileceği güvenli bir repository temeline oturtmak.

## Mevcut durum

- GitHub repository yerel çalışma alanına alınmıştır.
- Mevcut canlı sistem ve baseline adayı salt okunur referans kaynakları olarak belirlenmiştir.
- Core, runtime, kullanıcı verisi, türetilmiş veri ve secret sınırları tanımlanmıştır.
- Canlı sistem veya baseline içeriği henüz repository'ye aktarılmamıştır.

## İlk aşamanın kapsamı

1. Canlı sistem ile baseline dosyalarını sahiplik sınıflarına ayırmak.
2. Secret ve kişisel veri taraması yapmak.
3. Çalışan baseline'ı test sonuçlarıyla doğrulamak.
4. Güvenli repository yapısını ve ownership manifestini hazırlamak.
5. Kullanıcı onayından sonra yalnızca uygun core ve belge kaynaklarını aktarmak.

## Kapsam dışı

- Büyük bir mimari yeniden yazım.
- Canlı kullanıcı verisinin Git'e eklenmesi.
- Context Engine, Orchestrator veya Dependency Engine'in doğrudan uygulanması.
- Canlı sistem üzerinde deploy veya migration yapılması.

## Tamamlanma ölçütleri

- Aktarım adayları core, runtime, user-data, derived ve secrets olarak sınıflandırılmış olmalı.
- Baseline test komutları ve sonuçları kayıt altına alınmalı.
- Kullanıcı verisini koruyan güncelleme sözleşmesi makinece tanımlanmalı.
- Sonraki uygulama fazı kullanıcı tarafından onaylanmalı.
