# ADR-007 - KRCN CLI kurulum yaşam döngüsü

## Durum

Kabul edildi.

## Bağlam

KRCN Core komutları repository içinde `python tools/krcn.py` ile çalıştırılabiliyordu. Kullanıcının PowerShell, CMD, Git Bash, Codex, Claude, OpenCode veya başka bir istemci üzerinden herhangi bir proje dizininde yalnızca `krcn` komutunu kullanabilmesi için kullanıcı düzeyinde kalıcı bir kurulum sözleşmesi gerekiyordu.

CLI paketi, core repository ve kullanıcı verisi aynı fiziksel konum veya yaşam döngüsü değildir. Bunların birbirine karıştırılması, bir core güncellemesinin kullanıcı verisini taşıması veya farklı bir repository clone'unun yanlışlıkla kullanılmasına yol açabilir.

## Karar

1. `krcn`, tüm yerel istemciler için ortak ve ince komut satırı giriş noktası olacaktır.
2. Windows kurulumu repository içindeki `tools/install_cli.py` aracıyla yapılacaktır. Araç PowerShell, CMD ve Git Bash üzerinden aynı şekilde çağrılacak ve PowerShell script yürütme politikasına bağlı olmayacaktır.
3. Kurulum çevrimdışı wheel doğrulamasından sonra seçilen kullanıcı Python ortamına uygulanacaktır.
4. Kurulum, kullanılan core clone'unu kullanıcı düzeyindeki `KRCN_CORE_HOME` değeriyle kaydedecektir.
5. `KRCN_CORE_HOME` yalnızca sürümlenen core, şema, politika ve teknik bağlamın yerini gösterir.
6. `KRCN_HOME` kullanıcı verisinin yerini gösterir ve CLI kurulumu sırasında kendiliğinden oluşturulmaz, değiştirilmez veya taşınmaz.
7. Kurulum aracı gerekirse Python scripts dizinini kullanıcı PATH değerine kayıp oluşturmadan ekleyecektir.
8. Git pull kurulu CLI'ı sessizce değiştirmeyecektir. Onaylı core güncellemesinden sonra kurulum aracı yeniden çalıştırılacaktır.
9. CLI kaldırma veya yeniden kurma işlemi kullanıcı verisini, proje binding'lerini, backup dosyalarını ya da dış proje kaynaklarını silmeyecektir.
10. Repository dışından yapılan çağrı, çalışma dizininde bir KRCN Core bağlamı yoksa `KRCN_CORE_HOME` üzerinden aynı ortak application service katmanına ulaşacaktır.

## Sonuçlar

- Kullanıcı ve yapay zekâ istemcileri proje dizinine KRCN dosyası kopyalamadan aynı `krcn` komutunu kullanabilir.
- Core kodu, CLI kurulumu ve kullanıcı verisi bağımsız olarak yedeklenebilir, güncellenebilir ve doğrulanabilir.
- Bir repository clone'unun fiziksel yolu Git'e yazılmaz; yalnız kullanıcının yerel ortamında tutulur.
- Ortak kullanıcı veri köküne geçiş, CLI kurulumundan ayrı ve onaylı bir migration işlemi olarak kalır.
- Yeni terminal oturumları kullanıcı PATH ve `KRCN_CORE_HOME` değişikliklerini doğal biçimde devralır.
