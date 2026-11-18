# Decisions
- D1 Git author = repo owner (shreenig99); no AI attribution lines in commits (owner instruction overrides tool default).
- D2 Network: created a personal cloud env "StepThree" allowing openrouter.ai, generativelanguage.googleapis.com, api.groq.com; OpenRouter key injected by the proxy, never stored in repo.
- D3 Steps are 1-indexed; step 1 restates the problem and is trusted, so mutations use k >= 2.
- D4 Checker built before injector: the injector's gate depends on it.
