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
