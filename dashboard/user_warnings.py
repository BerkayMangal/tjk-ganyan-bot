"""Phase 5.2/5.3 kullanıcı koruma bildirimi.

Telegram mesajına geçici bir banner ekler. Phase 5.3 KARARI verildi (V5.1_DAR baz sistem).
TAM kaldırma Phase 5.4/5.5 (FLB/Benter prod'a alınınca): `PATCH_5_1_5_USER_WARNING` marker'ını
grep'le, import + çağrıyı kaldır, bu dosyayı sil. Phase 5.3.5'te flag-guarded tek-kupon ile
banner sadeleşir.

NOT: CLAUDE.md "yeni PATCH_* marker ekleme" der; bu marker bilinçli bir İSTİSNA
(geçici-kaldırılacak kodu işaretlemek için, Berkay'ın Phase 5.1.5 talimatı).
"""
import os

PATCH_5_1_5_USER_WARNING = "phase_5_2_calibration_period_banner"

WARNING_BANNER = """⚠️ TEK KUPON GEÇİŞİ (Phase 5.3 kararı)
Backtest tamamlandı: V5.1_DAR baz sistem (en ekonomik ~1000TL, en güvenilir).
V7 ve smart_genis emekliye ayrılıyor (referans — yakında kaldırılacak).
👉 V5.1_DAR oynayın; diğer kuponları dikkate almayın.
Detaylı plan: docs/PHASE_5_2_TO_5_9_ROADMAP.md (Phase 5.3)"""


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
