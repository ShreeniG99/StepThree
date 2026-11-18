# StepThree v0.1.0 plan

| # | Scope | Deliverable | Done when |
|---|-------|-------------|-----------|
| 1 | Data | `data/problems/*.json`: 50 problems (algebra / calculus / physics+units) | checker accepts all 50 clean |
| 2 | Inject | `stepthree/inject.py`: sign_flip, dropped_term, wrong_chain_rule, unit_mixup at step k, error propagated | each mutation unit-tested |
| 3 | Check | `stepthree/check.py`: expr (simplify, 20-pt numeric fallback), eq (solution sets), units (SI) | gate keeps item only if first break == k; >=200 kept, >=40/type |
| 4 | Eval | `stepthree/evaluate.py`: localization JSON + leakage (3 pressure msgs), deterministic leak detector, cache `runs/cache.jsonl` | dry-run 10, then seeded 50-item subset per free model |
| 5 | DeepTutor | separate venv, run same items, time-box 2h | results in runs/ or BLOCKERS.md; ISSUES/deeptutor.md |
| 6 | Ship | README + leaderboard + `results/chart.png` from runs/, pyproject, CLI, build+twine check, tag v0.1.0 | DoD all green |

Order: 1 -> 3 -> 2 (checker before injector, since the gate needs it) -> 4 -> 5 -> 6.
Steps are 1-indexed; step 1 is the setup copied from the statement and is never mutated (k >= 2).
Logs: PROGRESS.md (one line/iteration), DECISIONS.md, BLOCKERS.md, LEARNING.md (plain-English walkthrough).
