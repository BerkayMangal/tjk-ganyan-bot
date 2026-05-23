"""Phase 5.2 kalibrasyon dönemi kullanıcı koruma bildirimi.

Telegram mesajına Phase 5.3 sonrasında KALDIRILACAK geçici bir banner ekler.
Tek-kupon kararı verildikten sonra (Phase 5.3): `PATCH_5_1_5_USER_WARNING` marker'ını
grep'le, import + çağrıyı kaldır, bu dosyayı sil.

NOT: CLAUDE.md "yeni PATCH_* marker ekleme" der; bu marker bilinçli bir İSTİSNA
(geçici-kaldırılacak kodu işaretlemek için, Berkay'ın Phase 5.1.5 talimatı).
"""
import os

PATCH_5_1_5_USER_WARNING = "phase_5_2_calibration_period_banner"

WARNING_BANNER = """⚠️ KALİBRASYON DÖNEMİ (Phase 5.2)
Sistem 3 farklı kupon mantığı üretiyor (V5.1, V7, smart_genis).
Maliyet farkı büyük olabilir (~5x). Kalibrasyon tamamlanana kadar:
👉 V5.1_DAR baz alın, diğerleri referans.
Detaylı plan: docs/PHASE_5_2_TO_5_9_ROADMAP.md"""


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
