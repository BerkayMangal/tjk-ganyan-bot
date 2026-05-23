# Phase 1B.1 + 1E.0 — Karar Logu

Otonom yürütme. Kritik kararlar tek cümleyle.

## PART A — Shadow Rewire (multi_source_validator → expert_consensus)
- **Kaynak değişimi:** shadow artık `expert_consensus.build_consensus` çıktısını
  (`result['consensus']`, at-level) tüketiyor. multi_source_validator (altılı-varlık)
  shadow'dan çıkarıldı — ikincil sinyal olarak duruyor.
- **Duplicate yok:** consensus zaten `_try_consensus` ile hesaplanıyor (yerli_engine:2664);
  shadow'a PARAMETRE olarak pas geçildi. Yeni HTTP/fetch yok.
- **Sıra değişimi:** shadow kupon ÖNCESİnden consensus SONRASINA taşındı (consensus
  kupondan sonra hesaplanıyor). Read-only olduğu için kupon kararını etkilemez.
- **yerli_engine:** sadece `_process_proper_altili` (ana proper path) güncellendi;
  HTML-only/repaired path'lere shadow eklenmedi (scope dışı, Phase 1A ile tutarlı).
  Net değişim 10/10 satır (MAX 20 altında).
- **consensus_top_pick semantiği:** ayak-1 temsili (altılı tek-pick anlamsız); asıl
  veri `per_leg_consensus` (6 ayak). Eski Phase 1A alanları geriye-uyumlu türetildi
  (source_confidence = all_agree·1 + super_banko·0.66 normalize).
- **Ölü kod temizliği:** multi_source_validator cache makinesi (set/reset_validator_cache,
  _get_validation, _norm_hippo) kaldırıldı — artık kullanılmıyor.

## PART B — Bet Diary Scaffolding (Phase 1E.0)
- **CLV formülü DÜZELTİLDİ:** Plan `log(odds_close/odds_pred)` + "negatif" + "pozitif=onay"
  tutarsızdı. Finansal-doğru `log(odds_pred/odds_close)` uygulandı: 4.0→3.5 = +0.134
  (yüksek odds yakaladık = piyasa onayı). Test bunu doğruluyor.
- **Kapsam:** sadece dataclass + math + persistence + migration. Pipeline entegrasyonu
  ve bet_diary TABLOSUNA doğrudan yazım YOK → Phase 1E.1. Şimdilik JSONL + event_store
  (pipeline_events, event_type=bet_decision) dual-write.
- **bet_diary.py 184 satır** (250 sınırı altında, bölmeye gerek kalmadı).
- **P&L odds'tan hesaplanıyor** (payout'a bağımsız): win → stake·(odds−1), loss → −stake.
- **event_store'a 'bet_decision' event type eklendi.**
- Unit testler pytest'siz (assert + exit 0) — requirements'a ekleme yapılmadı.
