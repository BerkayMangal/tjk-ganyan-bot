"""Phase 5.1 — Altılı kupon simulation engine.

Tarihsel/forward altılı (race + sonuç) verildiğinde, üç kupon stratejisini uygula →
hit/payout/ROI dönder. Veri kaynağı agnostic (backfill VEYA forward bet_diary/live_tests).
Prod davranışını DEĞİŞTİRMEZ — sadece mevcut builder'ları read-only çağırır.
"""
