# Faz 7 ortak proje öğrenme servisi

## Sonuç

Otomatik proje öğrenme davranışı transport bağımsız `project.learn` operation olarak application service katmanına eklendi. CLI, SDK, MCP, plugin, Codex, Claude ve sonraki istemciler aynı request ile aynı exact planı alır.

## Kullanıcı girişleri

- `krcn project learn <dizin>` yalnızca proje dizinini alır.
- `krcn ask "<dizin> projesini öğren"` doğal dil isteğini çözümler.
- Dizin prompt içinde verilmemişse `krcn ask` için `--source <dizin>` kullanılabilir.

## Uygulama davranışı

- Workspace, project ve binding kimlikleri kullanıcıdan istenmez.
- Farklı desteklenen ifadeler aynı etkiler için aynı exact plan kimliğini üretir.
- Dry-run yalnız planı gösterir.
- Apply sırasında önceki exact plan kimliği ve tek approval kimliği zorunludur.
- Bütün istemciler aynı shared service ve authorization kapılarını kullanır.
- Kaynak dizin public response içinde gösterilmez ve proje dosyaları kopyalanmaz.
