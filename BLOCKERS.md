# Blockers / actions for the owner

## 0. Model runs: the OpenRouter key never reached this cloud session (blocks the leaderboard)
The key is saved on the "StepThree" environment, but every OpenRouter call from the session that
built the code returned `401 Missing Authentication header` for 70+ minutes (checked once a minute).
Docs say a saved key is picked up by a *new* session. No result has been invented: `runs/` is empty,
the README table says "No runs yet", and tag v0.1.0 was NOT created (Definition of Done not met).

Quota: 4 systems x (50 localization + 150 leakage) = 800 calls. Free OpenRouter accounts get
50 free-model requests/day (1000/day once you have bought $10 of credits, ever). At 50/day that is
~16 days; just rerun `stepthree eval` daily, as it resumes from `runs/cache.jsonl` and never re-sends a cached prompt.
If your account allows 1000/day, set `rpd: 1000` for openrouter in `config.yaml` first.

**Option A: new cloud session** in the StepThree environment on branch `claude/peaceful-euler-fj07eo`,
asking: "run the StepThree eval and report". (Any key value works there; the proxy swaps in the real one.)

**Option B: your own computer** (key never leaves your machine):
```bash
git clone https://github.com/shreenig99/stepthree && cd stepthree
git checkout claude/peaceful-euler-fj07eo
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest -q
export OPENROUTER_API_KEY=sk-or-...            # your key; never commit it
bash scripts/setup_deeptutor.sh                 # DeepTutor in its own venv; prints an export line
# paste the printed export line, then:
stepthree eval --dry-run                        # 10 items, check runs/*/ look sane
stepthree eval                                  # repeat daily until every row says Complete = yes
stepthree report                                # writes results/ and the README table
git add runs results README.md && git commit -m "Add benchmark runs and leaderboard" && git push
git tag v0.1.0 && git push origin v0.1.0        # only once the leaderboard has >= 3 complete systems
```

## Needs you
1. **PyPI upload** (not done, by instruction). From a clean checkout of tag v0.1.0:
   ```bash
   python -m pip install -U build twine
   python -m build
   python -m twine check dist/*
   python -m twine upload dist/*        # needs your PyPI API token
   ```
2. **File the DeepTutor issue** (not done, by instruction). Text: `ISSUES/deeptutor.md`.
   ```bash
   gh issue create --repo HKUDS/DeepTutor --title "deeptutor run --format json exits 0 when the turn fails" --body-file ISSUES/deeptutor.md
   ```
3. **Push the tag** if it is not on GitHub yet: `git push origin v0.1.0`
