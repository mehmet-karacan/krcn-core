# Faz 26 application ve CLI checkpoint

## Tamamlanan kapsam

- `outbound.assess` transport-neutral application operasyonu eklendi.
- ProviderRequest caller tarafindan degistirilemiyor; request digest yeniden
  uretiliyor ve exact ProviderApproval ile dogrulaniyor.
- Outbound response payload veya endpoint degeri gostermiyor.
- `sandbox.plan` salt okunur application operasyonu eklendi.
- Sandbox plani source path'i response'a koymuyor ve apply desteklemiyor.
- Zayif host profile planned yerine blocked donuyor.
- `krcn outbound assess` ve `krcn sandbox plan` request-file komutlari ile
  okunur tablo renderer'lari eklendi.
- Application request/response operation enumlari ve explicit handler registry
  ayni operasyon setine getirildi.
- Repository context yeni policy, spec ve schema kayitlarini canonical olarak
  gosteriyor.
- Doctor outbound default-deny ve secret remote deny politikasini dogruluyor.

## Dogrulama

- Phase 26 application/CLI + domain paketi: 20/20 gecti.
- Client-neutral outbound karar testi CLI, SDK ve OpenCode icin ayni sonucu
  verdi.
- Foundation, repository context, JSON, compile ve diff kontrolleri gecti.

## Sonraki adim

Faz 26 security matrisi, tam regression ve kapanis kaydini tamamla.

