"""FAZ D — Causal Modeling (counterfactual queries).

Mevcut V7 correlation-based. "Jokey değişse top-4 ihtimali ne olur?"
sorgu yapamaz. Bu paket o boşluğu doldurmaya çalışır:

  - propensity.py    : Propensity score matching (causal effect proxy)
  - counterfactual.py: "Eğer X olursa..." sorguları
  - forest.py        : Lightweight causal forest (saf Python)

Felsefe: tam causal inference pahalıdır (Pearl do-calculus, RCT). Biz
pratik approximation'lar yapıyoruz — observational data üzerinde
"as-if intervention" tarzı tahminler.

Berkay'ın asıl talebi: "ileriye yönelik". Counterfactual = en saf
forward-looking mantık. "Bu at + bu jokey + bu mesafede ne olur?"
"""
