# Faz 23 Adaptive Routing domaini

## Tamamlanan kapsam

- Strict `AdaptiveRoutingPolicy`, `RouteRequest`, `RouteDecision` ve shadow
  comparison domain kayitlari eklendi.
- Sekiz route modu work classification, delegation, model ve admission
  kararlarindan ayri tutuldu.
- Capability, recovery, secret, provider assurance, budget, authoritative
  context, source revision, sandbox, verifier ve approval hard gate'leri
  fail-closed uygulandi.
- Resource write conflict ve dependency sirasi paralel route'u engelliyor.
- Route, request, policy ve comparison kayitlari canonical SHA-256 digest ile
  baglandi.
- 16 senaryolu golden fixture ve negatif tamper testleri eklendi.

## Guvenlik sonucu

Route karari authority vermiyor, queue veya provider cagirmiyor, model
secmiyor ve mevcut coordinator davranisini degistirmiyor. Ham istek, model
output, source content, fiziksel path ve credential domain kayitlarina
alinmiyor.

## Sonraki checkpoint

`routing.decide` ve `routing.explain` application/CLI yuzeyleri ayni domain
servisine baglanacak. Ardindan Execution Coordinator yalniz shadow comparison
uretecek ve mevcut execution route'unu kullanmaya devam edecek.
