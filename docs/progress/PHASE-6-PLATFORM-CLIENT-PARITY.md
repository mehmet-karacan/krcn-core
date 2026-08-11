# Faz 6 platform ve istemci eşitliği

## Sonuç

Windows ve macOS fiziksel kullanıcı evi varsayımları aynı mantıksal layout ve portable manifest sözleşmesine bağlandı. CLI, SDK, MCP, plugin, Codex, Claude ve gelecekteki istemciler aynı application service factory ve operation kümesini kullanıyor.

## Doğrulanan davranış

- Açık data root bütün platform varsayımlarından önce gelir.
- `KRCN_HOME` repository clone yolundan bağımsızdır.
- Archive path değerleri yalnız forward slash kullanan relative kayıtlardır.
- Farklı kullanıcı evi ve proje path değerleri aynı mantıksal veri için aynı backup kimliğini üretir.
- `client_kind` değişikliği plan veya güvenlik davranışını değiştirmez.
- Application request şeması runtime tarafından desteklenen bütün operation değerlerini kapsar.
- CLI ürün kuralı içermez; `create_application_service` üzerinden ortak servisi çağırır.

