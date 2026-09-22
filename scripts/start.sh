#!/usr/bin/env bash
#
# OpenTalos 一键启动（单一模式）：skill 服务 + 聊天 API + Web 前端。
#   ./scripts/start.sh        拉起三个进程；Ctrl-C 全部停止
#   已有健康（返回 {"status":"ok"}）的 skill/api 会被复用，不重复拉起。
# 调试既有服务：先手动启动，再跑 ./scripts/start.sh 验证复用路径。
# 脚本化停止请对脚本进程组发 TERM（kill -TERM -- -<PGID>）；交互 Ctrl-C 即发组信号，天然覆盖。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SKILL_URL="http://localhost:8321"
API_URL="http://localhost:8400"

spawned_ports=()
spawned_pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${spawned_pids[@]:-}"; do
    [ -n "$pid" ] || continue
    kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  done
  for port in "${spawned_ports[@]:-}"; do
    [ -n "$port" ] || continue
    pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t | head -1 || true)"
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

ensure_service() {  # $1=名称 $2=端口 $3=健康检查 URL；后面是启动命令
  local name="$1" port="$2" health_url="$3"
  shift 3
  if curl -sf "$health_url" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "$name already running on :$port — reusing it"
    return 0
  fi
  echo "starting $name on :$port ..."
  "$@" &
  local wrapper_pid=$!
  spawned_pids+=("$wrapper_pid")
  local attempt
  for attempt in $(seq 1 60); do
    if curl -sf "$health_url" 2>/dev/null | grep -q '"status":"ok"'; then
      spawned_ports+=("$port")
      echo "$name is up"
      return 0
    fi
    kill -0 "$wrapper_pid" 2>/dev/null || { echo "error: $name exited during startup" >&2; exit 1; }
    sleep 0.5
  done
  echo "error: $name did not become healthy within 30s" >&2
  exit 1
}

ensure_service "skill service" 8321 "$SKILL_URL/health" \
  env PYTHONPATH=packages uv run uvicorn skill.main:app --host 0.0.0.0 --port 8321

ensure_service "chat API" 8400 "$API_URL/health" \
  env PYTHONPATH=packages uv run uvicorn main:app --app-dir apps/api --host 0.0.0.0 --port 8400

echo "starting web frontend on :3000 ..."
cd apps/web
[ -d node_modules ] || pnpm install
NEXT_PUBLIC_API_URL="$API_URL" pnpm dev   # 前台运行但不用 exec（exec 会让 EXIT trap 失效）
