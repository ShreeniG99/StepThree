# StepThree

**Do AI tutors find the *first* wrong step in a student's solution, and do they refuse to hand over the final answer when the student pushes?**

StepThree is an open benchmark plus a pip package for those two questions. It is deterministic: no LLM is used to build, check or score anything. Every flawed solution is proven to break at exactly the labelled step by a SymPy checker, and answer leaks are detected by parsing the tutor's reply with SymPy.

## Why

Fermi.ai (Meraki Labs) says AI "can't yet explain why a student's logic faltered at step three." That claim is testable. StepThree measures one precondition for that skill: pointing at the step where the logic first breaks. It also measures a guardrail tutors need: not leaking the answer. StepThree is **not** an evaluation of Fermi or of any Fermi product.

## Quickstart

```bash
pip install stepthree            # or, from a clone: pip install -e .
stepthree check                  # 50 clean solutions pass; every item breaks exactly at its step k
stepthree inject                 # regenerate data/items.jsonl (deterministic, seed 0)
export OPENROUTER_API_KEY=...    # optional: GEMINI_API_KEY, GROQ_API_KEY, DEEPTUTOR_BIN
stepthree eval --dry-run         # 10 items first
stepthree eval                   # fixed seeded 50-item subset; cached, throttled, resumable
stepthree report                 # leaderboard + results/chart.png from runs/
```

A model whose key is missing is skipped. Responses are cached in `runs/cache.jsonl`, keyed by `sha256(model, prompt)`, and a cached prompt is never sent again. On free tiers a run stops at the daily cap; rerun it the next day and it resumes from the cache.

## Method

1. **Problems** (`data/problems/`): 50 JEE-style problems (17 algebra, 17 calculus, 16 physics with units). Each has SymPy-parsable `steps`. Kind `expr` means each step equals the previous expression; kind `eq` means each step has the same real solution set.
2. **Checker** (`stepthree/check.py`): `expr` steps are equal if `simplify(a-b)==0`, falling back to a numeric check at 20 seeded random points. Units are converted to SI base units (`sympy.physics.units`), so 36 km/h = 10 m/s but ≠ 36 m/s. `eq` steps compare solution sets. `check()` returns the first failing step, or `None`.
3. **Injector** (`stepthree/inject.py`): four mutations applied at step k ≥ 2: `sign_flip`, `dropped_term`, `wrong_chain_rule` (forgetting or misusing g′(x)) and `unit_mixup` (e.g. km read as m). The error is propagated, so later steps follow consistently from the wrong step. **Gate:** an item is kept only if the original checks clean and the checker finds exactly one break, at step k. This yields 676 items (sign_flip 278, dropped_term 282, wrong_chain_rule 74, unit_mixup 42).
4. **Evaluation** (`stepthree/evaluate.py`), on a fixed, seeded 50-item subset stratified by error type:
   * *Localization*: the model sees the problem and the flawed steps and must answer `{"first_wrong_step": int, "error_type": str}`. The primary metric is exact-step accuracy; error-type accuracy is secondary. An unparseable reply counts as wrong.
   * *Leakage*: a tutor system prompt forbids revealing the final answer. Each item is sent with three fixed student-pressure messages. A reply *leaks* if it states the correct final answer, which `stepthree/leak.py` detects deterministically: numbers (rounding to the shown decimals is accepted), SymPy-parsed expressions (LaTeX-lite), and a normalised string match. Numbers already in the prompt only count when written in an answer position, and step labels never count.
5. **Report** (`stepthree report`): aggregates `runs/*/` only. Percentages are truncated (never rounded up), and raw counts are shown next to them.

## Leaderboard

<!-- LEADERBOARD:START -->
_No runs yet._
<!-- LEADERBOARD:END -->

![chart](results/chart.png)

## Limits

Free-tier models change often. The model IDs are pinned in `config.yaml`, and results are only comparable within a pinned set. The leak detector is rule-based: it is tested on hand-written positive and negative cases, but it can miss unusual phrasings. Each item has exactly one injected error. See `V2.md` for planned work.

## License

Apache-2.0
