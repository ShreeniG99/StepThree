# Learning log: how StepThree was built, step by step

This file explains every step in plain English so you can describe the project yourself.
New entries are added at the bottom as the work progresses.

## The idea in one paragraph
A student writes a worked solution: step 1, step 2, step 3 and so on. A good tutor should
(1) point at the *first* step where the logic breaks, and (2) *not* just hand over the final
answer when the student begs. StepThree is a **benchmark**: a fixed test set plus a scoring
program, so different AI tutors can be compared fairly on exactly those two skills.

## Glossary (words people throw around)
- **API**: a web address a program sends requests to (instead of a human clicking). "Call the
  OpenRouter API" = our Python code sends the prompt over HTTPS and gets the model's reply as JSON.
- **API key**: a password for an API. Never put it in code or git; anyone who sees it can spend your quota.
- **SDK** (Software Development Kit): a library that wraps an API so you call `client.chat(...)`
  instead of building raw HTTP requests. We use plain `requests` instead, so there are fewer dependencies.
- **MCP** (Model Context Protocol): a standard way to plug *tools* (GitHub, Slack, a database)
  into an AI assistant. Claude used MCP tools in this session (e.g. to manage the cloud environment).
  StepThree itself doesn't use MCP.
- **Free tier / rate limit**: free model access is capped, e.g. "20 requests per minute,
  N per day". **Throttling** means our code deliberately waits between calls to stay under the cap.
- **Cache**: we save every model reply in `runs/cache.jsonl`, keyed by a hash of (model, prompt).
  If we run again, we reuse the saved reply instead of calling the API again. This saves quota and lets
  a run resume across days.
- **Hash**: a fixed-length fingerprint of some text (e.g. SHA-256). Same text gives the same hash.
- **SymPy**: a Python library for symbolic maths. It can check that `2*(x+1)` equals `2*x+2` exactly.
- **Deterministic**: gives the same answer every time, with no randomness and no AI judging. All our scoring
  is deterministic, which is what makes the benchmark trustworthy.
- **Seed**: a number that fixes "random" choices so they are reproducible (e.g. which 50 items are sampled).
- **JSON / JSONL**: a text format for data. JSONL = one JSON object per line (easy to append to).
- **Unit test / pytest**: small programs that check our code does what we claim. `pytest -q` runs them all.
- **Package / pip / PyPI**: a package is installable code. `pip install` fetches from PyPI (the
  public Python package index). `pyproject.toml` describes our package; `python -m build` creates
  the installable files; `twine check` validates them before upload.
- **CLI**: command-line interface, e.g. `stepthree check`.
- **venv**: an isolated Python install for one project, so library versions don't clash.
- **CI/CD**: Continuous Integration / Continuous Delivery. A server (e.g. GitHub Actions) automatically
  runs the tests on every push (CI) and can publish releases (CD). Not in v0.1.0 (see V2.md).
- **Git tag**: a named bookmark on a commit, e.g. `v0.1.0` = "this exact code is release 0.1.0".
- **Proxy**: a middleman that all web traffic passes through. In this cloud session it enforces an
  allow-list of websites and injects your API key so the code never sees it.

## Step log
1. **Git identity.** Commits are authored as you (`shreenig99`), with no AI attribution lines.
2. **Sandbox network.** The cloud machine could only reach package sites. We created an environment
   "StepThree" that also allows openrouter.ai, Gemini and Groq. Your OpenRouter key was entered in a
   secure form and is attached to requests by the proxy, so it never appears in code.
3. **Free model check.** We asked OpenRouter which models are free *today* (the list changes often).
4. **Plan files.** PLAN.md (what/when), DECISIONS.md (choices and why), PROGRESS.md (one line per
   iteration), this file. `.gitignore` lists files git must never save (e.g. `.env` with keys).
5. **Problems (data/problems/).** 50 hand-written problems. Each step is written in SymPy syntax so a
   computer can check it, e.g. `36*kilometer/hour + 10*meter/second`.
6. **Checker (check.py).** For two consecutive steps it asks: are they mathematically the same? It first tries
   algebra (`simplify(a-b)==0`); if SymPy can't prove it, it plugs in 20 random numbers and compares.
   Units are converted to metres/kilograms/seconds first, which is how it knows 36 km/h = 10 m/s.
   Equations are compared by their *solution sets*. Result: all 50 clean solutions pass.
7. **Injector (inject.py).** Takes a correct solution, breaks step k on purpose (flip a sign, drop a term,
   forget the chain rule's inner derivative, use the wrong unit), then rewrites later steps so they follow
   from the mistake, like a real student would. **Gate:** we only keep an item if the checker independently
   finds exactly one broken step, and it is k. 676 items survived (needed >= 200).
8. **Tests (pytest).** ~740 automated checks: every problem passes clean, every item breaks exactly at k,
   every mutation type works, the leak detector handles 27 hand-written replies correctly.
   A **failing test written first, then code to make it pass** is called test-driven development.
9. **Leak detector (leak.py).** Reads a tutor reply and decides, by rules (no AI), whether it gave away the
   answer. Tricky parts: "step 3" is not the answer 3; repeating a number from the question is not a leak
   unless it's written as the answer ("= 20"); LaTeX like `\frac{125}{9}` must be understood.
10. **Harness (evaluate.py).** Sends prompts to models over HTTPS. *Cache*: replies saved and reused.
    *Throttle*: waits 60/rpm seconds between calls. *Daily budget*: stops cleanly at the free-tier cap
    and resumes tomorrow. Tested with a **fake API** (a stand-in function) so tests cost nothing.
11. **Report (report.py).** Builds the leaderboard table and chart only from saved results in `runs/`,
    so every number can be traced back to a real model reply.
12. **Packaging.** `pyproject.toml` describes the package; `python -m build` makes a *wheel* (.whl, the
    installable file) and an *sdist* (source archive); `twine check` validates them. We installed the wheel
    into a brand-new venv and ran `stepthree check` from an empty folder; it worked. That's the
    "works on someone else's machine" test.
13. **DeepTutor.** An open-source AI tutor. Installed in its *own* venv (so its many libraries don't clash
    with ours), configured to use the same free Gemma model through OpenRouter, and driven through its CLI.
    Comparing "Gemma raw" vs "DeepTutor on Gemma" shows what DeepTutor's tutoring layer adds or removes.
14. **Blocked on the key, and why we stopped instead of faking it.** The key is stored on the cloud
    environment, but this session's proxy never attached it (every call: `401 Missing Authentication header`).
    A benchmark's whole value is that every number traces back to a real reply, so the leaderboard stays
    empty rather than estimated. BLOCKERS.md has two ways forward: a new cloud session (which picks up the
    key), or running on your own laptop. **Rate limits in practice:** 800 calls at 50/day ≈ 16 days; the
    cache means each daily rerun continues where the last stopped. `scripts/setup_deeptutor.sh` is a
    **shell script**: a recorded list of terminal commands so anyone can repeat the DeepTutor install exactly.
15. **A second, "real students" track (MathEDU).** We checked nine published datasets; only MathEDU had
    real student working *and* a marked error location *and* text we can feed to text-only models. Words:
    - **Licence:** the legal terms for reusing data or code. *No licence file* means "all rights reserved" by
      default, so we don't copy it into our repo; our code downloads it on the user's machine instead.
    - **Pinned commit:** we download one exact version (a git commit id) so results are reproducible
      even if the authors change their files later.
    - **Gold label:** the "correct answer" a model is scored against. Here it comes from teachers, not SymPy.
    - **Baseline:** the score of a dumb strategy (e.g. "always say step 1"). A model is only impressive if
      it beats the baseline. On real data ~40% of errors are at step 1, so this matters a lot.
