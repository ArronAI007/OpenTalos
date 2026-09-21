#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

usage() {
  cat <<'EOF'
Usage: scripts/start.sh [chat|skill]

  chat   Start the Gradio chat console (apps/chat_console/app.py). Default.
  skill  Start the skill FastAPI service (packages/skill) via uvicorn.
         Requires Docker running (it sandboxes skill-script execution
         in containers).

packages/core/model_client.py loads MODEL_PROVIDER/MODEL_API_KEY/MODEL_NAME/...
from .env itself (see .env.example) — values already in your shell
environment take precedence over it.
EOF
}

target="${1:-chat}"

case "$target" in
  -h|--help)
    usage
    exit 0
    ;;
  chat|skill)
    ;;
  *)
    echo "error: unknown target '$target'" >&2
    usage
    exit 1
    ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not installed — see https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [ "$target" = "chat" ]; then
  exec uv run python apps/chat_console/app.py
fi

# target == skill
if ! docker info >/dev/null 2>&1; then
  echo "error: docker isn't running — the skill service needs it to sandbox script execution" >&2
  exit 1
fi

exec env PYTHONPATH=packages uv run uvicorn skill.main:app --host 0.0.0.0 --port 8000
