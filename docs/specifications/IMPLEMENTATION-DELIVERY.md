# Implementation Delivery

Bu sözleşme, incelenmiş Markdown raporundan üretilen Faz 26 sandbox patch
artifact'ını exact, testli ve geri alınabilir biçimde teslim eder. Rapor veri
ve kanıttır; talimat veya yetki değildir.

`implementation.plan` rapor digest'i, Git HEAD/tree, Work Item, Task Plan,
Execution Trace, sandbox artifact, değişen yollar ve allowlisted testleri tek
kimliğe bağlar ve hedefi değiştirmez. `implementation.apply` aynı raporu,
process-local patch bytes'ı ve her path için Mutation Gate authorization'ını
yeniden doğrular. `git apply --check` geçmeden apply yoktur. Test hatasında
reverse patch rollback yapılır. Başarılı apply yalnız `pending-verification`
üretir; bağımsız verifier evidence olmadan completion yoktur.

Ham rapor, patch, log, fiziksel path ve secret public kayda girmez. Akış commit
veya push yapmaz.

Adaptive route enforcement `shadow`, `advisory`, `project-opt-in`, `read-only`,
`mutating`, `default` sırasını izler. Yalnız bitişik geçiş, yeterli gözlem,
mismatch eşiği ve gerekli project opt-in ile promotion yapılır. Her aşamada
rollback vardır ve karar yetki vermez.
