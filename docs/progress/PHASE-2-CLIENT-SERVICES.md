# Faz 2 ortak istemci servisleri

## Amaç

CLI, SDK, MCP, plugin ve yapay zekâ istemcilerinin onboarding, listeleme, inceleme ve yeniden tarama işlemlerinde aynı servis sözleşmesini, policy değerlendirmesini ve mutasyon kapısını kullanmasını sağlamak.

## Uygulanan davranış

1. `project.list`, `project.inspect`, `project.onboard` ve `project.rescan` işlemleri tek bir application service üzerinden çalışır.
2. Taşınabilir kimliği olan yeni bir istemci core değişikliği gerektirmeden bağlanabilir; istemci türü güvenlik kararına etki etmez.
3. Listeleme ve inceleme sonuçlarında fiziksel source locator değeri gösterilmez.
4. Onboarding ve rescan ilk çağrıda yalnızca plan üretir.
5. Uygulama çağrısı, önceki dry-run sonucundaki plan kimliğini birebir istemek zorundadır.
6. User-data değişikliği ayrıca açık bir approval kimliği gerektirir.
7. Rescan, adapter capability ve kullanıcı policy kapısını servis içinde çalıştırır.
8. CLI yalnızca transport adapter'ıdır; servis kurallarını yeniden tanımlamaz.
9. MCP, SDK ve plugin uygulamaları `src/krcn_core/application.py` içindeki aynı `ServiceRequest` ve `ServiceResponse` sözleşmelerini kullanır.
10. Kaynak dizin salt okunur kalır ve genel yanıtlara makineye özel yol taşınmaz.

## CLI kullanım modeli

Kayıtlı projeleri listelemek için:

```bash
krcn project list
```

Bir projeyi fiziksel locator değerini göstermeden incelemek için:

```bash
krcn project inspect <project-id>
```

Onboarding planı üretmek için:

```bash
krcn project onboard --workspace-id <workspace-id> --project-id <project-id> --binding-id <binding-id> --name <project-name> --source <source-directory>
```

Plan incelendikten sonra aynı onboarding işlemini uygulamak için ilk yanıttaki plan kimliği kullanılır:

```bash
krcn project onboard --workspace-id <workspace-id> --project-id <project-id> --binding-id <binding-id> --name <project-name> --source <source-directory> --apply --expected-plan <plan-id> --approval-id <approval-id>
```

Rescan için de önce plansız yazma yapmayan çağrı, ardından aynı plan kimliğine bağlı uygulama çağrısı kullanılır:

```bash
krcn project rescan <project-id>
krcn project rescan <project-id> --apply --expected-plan <plan-id> --approval-id <approval-id>
```

## Sonraki adım

Ortak servis sözleşmesi uçtan uca sentetik fixture'larla sınanacak. Kaynağa yazmama, locator maskeleme, istemciden bağımsız policy davranışı, yanlış plan reddi ve çevrimdışı çalışma birlikte doğrulanacak.
