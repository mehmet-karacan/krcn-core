# Faz 18 Research Orchestration V1A

## Sonuç

Kullanıcı aracılı araştırma akışının ilk çalışan dilimi tamamlandı.

KRCN Core artık:

- proje veya global kapsamda araştırma çalışması hazırlayabilir,
- researcher, architecture reviewer, critic, synthesizer ve citation verifier rolleri için taşınabilir prompt paketleri üretebilir,
- dış istemcilerden dönen Markdown sonuçlarını güvensiz kullanıcı verisi olarak exact plan ve onay kapısından geçirerek içe alabilir,
- kaynak, iddia ve çelişki kayıtlarını yapılandırılmış JSON ile izleyebilir,
- araştırma durumunu ham içerik veya makine yolu sızdırmadan gösterebilir.

CLI yüzeyi:

```text
krcn research prepare --request-file <request.json>
krcn research import-response --request-file <request.json>
krcn research status --request-file <request.json>
```

## Güvenlik sınırları

- Hazırlama ve içe aktarma user-data mutasyonudur. Exact plan ve açık onay zorunludur.
- Harici model yanıtı hiçbir zaman yetki veya doğrulanmış bilgi sayılmaz.
- Ham araştırma yanıtları project capsule içine alınmaz.
- Restore edilen kapsülde dışlanan ham yanıtlar digest bağlı dependency olarak görünür ve durum sorgusu degraded-safe çalışır.
- Secret, makineye özgü mutlak yol, symlink ve Windows junction kaçışları fail-closed reddedilir.
- Gemini opsiyoneldir. Bulunmaması araştırma akışını engellemez ve yeni API maliyeti oluşturmaz.
- V1A yeni vector DB, RAG, graph DB veya provider API bağımlılığı eklemez.

## Doğrulama

- Tam regresyon: 756 başarılı, 4 ortam kaynaklı skip
- Hedefli kabul: 42 başarılı, 1 ortam kaynaklı skip
- Repository, JSON biçimi, context, compileall ve diff kontrolleri başarılı
- Bağımsız verifier incelemesinde açık P1 veya P2 bulgu kalmadı

## Sonraki adımlar

1. Gerçek bir gpu-fusion araştırma talebiyle operator-mediated pilot çalıştır.
2. Araştırma bulgularının ayrı onayla knowledge kaydına yükseltilmesi akışını ekle.
3. OpenCode, Codex CLI ve Claude CLI için explicit execution adapter sözleşmesini uygula.
4. Native delegated work unit sonuçlarını runtime queue, lease, fencing ve bağımsız verifier zincirine bağla.
5. Proje bazlı benchmark scorecard ve model atamasını araştırma workload profillerinde kullan.
