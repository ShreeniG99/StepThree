# Blockers / actions for the owner

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
