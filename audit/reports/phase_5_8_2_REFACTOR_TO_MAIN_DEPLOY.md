# Phase 5.8.2 — Refactor → Main Merge + Railway Deploy

## Merge öncesi state
- origin/main 1cd9d46 (8 tur geride — sabah V7 sızıntısının sebebi).
- refactor 106 commit ÖNDE; **origin/main, refactor'ın DİREKT ATASI** (merge-base==origin/main).
- → conflict OLMADI (refactor ⊇ main). Temiz --no-ff merge.

## Yapılanlar
- Backup tag: `pre-merge-2026-05-24-main-backup` (origin/main 1cd9d46) + `-refactor-backup` (push'lu).
- Merge: `git merge refactor --no-ff` → merge commit **ffa1c85** (0 conflict).
- Push: `1cd9d46..ffa1c85 main → main` → Railway auto-deploy tetiklendi.
- Code defaults doğrulandı (TJK_KUPON_MODE=v5_1_only / TJK_V9_LIVE=1 / HEAVY_FAV_PCT=50). compile OK.

## Smoke (deploy sırasında)
- `/api/health`: status ok, scheduler/scraper/yerli_engine=true, v=5.1 (muhtemelen ESKİ deploy hâlâ
  serve; yeni build ~3-5dk). Servis AYAKTA.
- Railway dashboard = otoritatif (build success + logs).

## Rollback (gerekirse)
- Build patlarsa: `git revert ffa1c85 --no-edit && git push origin main` → eski deploy.
- Backup tag: `git checkout pre-merge-2026-05-24-main-backup`.
- Runtime v9 hatası: V5.1 fallback OTOMATİK (PATCH_5_7_0/5_7_5) — sistem çalışır.
- Acil: Railway env `TJK_V9_LIVE=0` → V5.1.

## Berkay AKSİYON (13:30 İstanbul öncesi)
1. Railway dashboard → Deployments → son deploy **success** mi? (build ~3-5dk).
2. Logs: "v9" / "PATCH_5_6_5" görünmeli; "V7 kupon" GÖRÜNMEMELİ.
3. ~13:15 Telegram'da kupon bekle: v9 router (Tam Sistem ağırlıklı), V7 YOK.
4. V7 hâlâ varsa → env `TJK_KUPON_MODE=v5_1_only` set + restart (ama default zaten bu, gerekmemeli).
