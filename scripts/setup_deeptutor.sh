#!/usr/bin/env bash
# Install DeepTutor 1.7.3 in its own venv and point it at the same free Gemma model via OpenRouter.
# Usage: OPENROUTER_API_KEY=... bash scripts/setup_deeptutor.sh   (then export the printed variables)
set -euo pipefail
DT_VENV=${DT_VENV:-$HOME/.stepthree-dtvenv}
export DEEPTUTOR_HOME=${DEEPTUTOR_HOME:-$HOME/.stepthree-dthome}
python3 -m venv "$DT_VENV"
"$DT_VENV/bin/pip" install -q "deeptutor==1.7.3"
mkdir -p "$DEEPTUTOR_HOME"
cat > "$DEEPTUTOR_HOME/setup.json" <<'J'
{"llm": {"provider": "openrouter", "model": "google/gemma-4-31b-it:free", "api_key_env": "DT_LLM_KEY", "api_format": "openai_chat"}}
J
"$DT_VENV/bin/deeptutor" init --non-interactive
"$DT_VENV/bin/deeptutor" config apply "$DEEPTUTOR_HOME/setup.json"
echo "export DEEPTUTOR_BIN=$DT_VENV/bin/deeptutor DEEPTUTOR_HOME=$DEEPTUTOR_HOME DT_LLM_KEY=\$OPENROUTER_API_KEY"
