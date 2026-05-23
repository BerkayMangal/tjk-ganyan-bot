"""Phase 5.2/5.3.5 kullanıcı koruma bildirimi.

Telegram mesajına geçici bir banner ekler. Phase 5.3.5'te retirement EXEC edildi → kullanıcı
artık TEK kupon (V5.1) görüyor (TJK_KUPON_MODE=v5_1_only). Banner artık 3-kupon UYARISI değil,
sade kalibrasyon-dönemi BİLGİSİ. TAM kaldırma: FLB/Benter prod'a alınınca (Phase 5.5 aktivasyon
/ 5.4) → `PATCH_5_1_5_USER_WARNING` grep'le, import+çağrı kaldır, bu dosyayı sil.

NOT: CLAUDE.md "yeni PATCH_* marker ekleme" der; bu marker bilinçli bir İSTİSNA
(geçici-kaldırılacak kodu işaretlemek için, Berkay'ın Phase 5.1.5 talimatı).
"""
import os

PATCH_5_1_5_USER_WARNING = "phase_5_2_calibration_period_banner"

WARNING_BANNER = """ℹ️ V5.1 TEK KUPON (kalibrasyon dönemi)
Sistem artık tek kupon üretiyor (V5.1). V7/smart_genis sadeleştirme için kaldırıldı.
Model kalibrasyonu sürüyor; FLB düzeltici shadow'da test ediliyor (henüz aktif değil)."""


def get_banner() -> str:
    """Banner metnini döndürür (flag açıksa), aksi halde boş string.

    Env: TJK_PHASE_5_2_WARNING (default '1' = açık). Phase 5.3 sonrası '0' yap
    veya bu modülü kaldır. Asla raise etmez.
    """
    try:
        if os.getenv("TJK_PHASE_5_2_WARNING", "1") == "1":
            return WARNING_BANNER + "\n\n"
    except Exception:
        pass
    return ""
