# Ready-to-file issues for HKUDS/DeepTutor

## 1. `deeptutor run ... --format json` exits 0 when the turn fails

**Version:** deeptutor 1.7.3 (PyPI core wheel), Python 3.13, Linux.

**Steps to reproduce**
```bash
python -m venv dt && dt/bin/pip install deeptutor==1.7.3
export DEEPTUTOR_HOME=$PWD/dthome DT_LLM_KEY=invalid
dt/bin/deeptutor init --non-interactive
echo '{"llm":{"provider":"openrouter","model":"google/gemma-4-31b-it:free","api_key_env":"DT_LLM_KEY","api_format":"openai_chat"}}' > setup.json
dt/bin/deeptutor config apply setup.json
dt/bin/deeptutor run chat "hi" --format json; echo "exit=$?"
```

**Actual:** stdout ends with `{"type": "error", ... "content": "Error code: 401 ..."}` and
`{"type": "done", ... "metadata": {"status": "failed", ...}}`, but the process exits with **code 0**.

**Expected:** a non-zero exit code when the terminal event has `status: failed`, so that agents and
shell pipelines (the README's "Let an agent drive it" use case, e.g. `SID=$(deeptutor run ... | jq ...)`)
can detect failure without parsing every event.

**Note:** NDJSON on stdout stays clean (the traceback goes to stderr), which is good.
