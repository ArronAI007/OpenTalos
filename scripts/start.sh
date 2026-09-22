#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

usage() {
  cat <<'EOF'
Usage: scripts/start.sh

One command starts everything the chat experience needs:
  1. the skill FastAPI service (packages/skill via uvicorn, :8321) in the
     background — skipped if something already answers on its /health
  2. the Gradio chat console (apps/chat_console/app.py, :7860) in the foreground
Ctrl-C stops both (a service you started yourself beforehand is left alone).

Skill scripts run as local subprocesses (a proper sandbox will be
reintroduced separately later). To debug the service in isolation:
  env PYTHONPATH=packages uv run uvicorn skill.main:app --port 8321

packages/core/model.py loads MODEL_PROVIDER/MODEL_API_KEY/MODEL_NAME/...
from .env itself (see .env.example) — values already in your shell
environment take precedence over it.
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "error: unexpected argument '${1}'" >&2; usage; exit 1 ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not installed — see https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

SKILL_URL="http://localhost:8321"

# 必须确认是本服务的 health 响应，而不是端口上恰好有别的 HTTP 服务
# （比如另一个 FastAPI 应用的 404 也是 2xx 之外的响应，但一个返回 200 的陌生服务更危险：
#  宽松的 curl -sf 会把它误认成"已在运行"，聊天时就全打到别人身上去了）。
skill_healthy() {
  local body
  body="$(curl -sf "$SKILL_URL/health" 2>/dev/null)" || return 1
  case "$body" in
    *'"status":"ok"'*) return 0 ;;
    *) return 1 ;;
  esac
}

skill_pid=""
if skill_healthy; then
  echo "skill service already running at $SKILL_URL — reusing it, will not stop it on exit"
else
  echo "starting skill service at $SKILL_URL ..."
  env PYTHONPATH=packages uv run uvicorn skill.main:app --host 0.0.0.0 --port 8321 &
  skill_pid=$!
  # 注意不能 exec 聊天进程：exec 会替换掉本 shell，trap 失效，服务就成孤儿了。
  cleanup() {
    trap - EXIT INT TERM
    if [ -n "$skill_pid" ]; then
      kill "$skill_pid" 2>/dev/null || true
      wait "$skill_pid" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT INT TERM
  for _ in $(seq 1 50); do
    if skill_healthy; then break; fi
    if ! kill -0 "$skill_pid" 2>/dev/null; then
      echo "error: skill service failed to start (see output above)" >&2
      exit 1
    fi
    sleep 0.2
  done
  if ! skill_healthy; then
    echo "error: skill service did not become healthy within 10s" >&2
    exit 1
  fi
  # $! 是 `uv run` 包装进程的 PID，杀掉它不保证带走 uvicorn 子进程（实测会变成孤儿）。
  # 改成找出真正监听该端口的进程——能走到这里，/health 已经是它应答的，必然是我们刚拉起的实例。
  skill_pid="$(lsof -nP -iTCP:8321 -sTCP:LISTEN -t | head -1)"
fi

uv run python apps/chat_console/app.py
