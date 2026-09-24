#!/usr/bin/env bash
#
# OpenTalos 一键管理（后台模式）：skill 服务 + 聊天 API + Web 前端。
#   ./scripts/start.sh          拉起三个进程到后台（日志 .data/logs/，pid 记录 .data/pids/），
#                               全部健康后打印地址并退出，终端立即归还
#   ./scripts/start.sh stop     停止本脚本拉起的进程（复用的外部进程不动）
#   ./scripts/start.sh restart  先停后起，等价于 stop + start
#   tail -f .data/logs/web.log  查看某一路日志
# 已有健康（返回 {"status":"ok"}）的 skill/api（或首页可访问的 web）会被复用，不重复拉起，
# 也不归本脚本的 stop 管理。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ACTION="${1:-start}"
case "$ACTION" in
  start|stop|restart) ;;
  *) echo "usage: $0 [start|stop|restart]" >&2; exit 2 ;;
esac

PID_DIR=".data/pids"

# 只动 .data/pids/ 里记录的 PID 与端口：复用的外部进程（非本脚本拉起）没有记录，天然不受影响。
do_stop() {
  local stopped=""
  local pid_file name pid port port_pid
  for pid_file in "$PID_DIR"/*.pid; do
    [ -e "$pid_file" ] || break  # 无匹配时 glob 原样保留，直接退出循环
    name="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      stopped="$stopped $name"
    fi
    # 顶层命令是 uv/pnpm 包装，实际监听者可能是孙进程、pid 那一杀漏网：按记录的端口补杀
    port="$(cat "$PID_DIR/$name.port" 2>/dev/null || true)"
    if [ -n "$port" ]; then
      port_pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
      if [ -n "$port_pid" ]; then
        kill "$port_pid" 2>/dev/null || true
        stopped="$stopped $name"
      fi
    fi
    rm -f "$pid_file" "$PID_DIR/$name.port"
  done
  if [ -n "$stopped" ]; then
    echo "stopped:$stopped"
  else
    echo "nothing to stop (no records in $PID_DIR)"
  fi
}

if [ "$ACTION" != "start" ]; then
  do_stop
  [ "$ACTION" = "stop" ] && exit 0
fi

SKILL_URL="http://localhost:8321"
API_URL="http://localhost:8400"
WEB_PORT="${PORT:-3010}"
LOG_DIR=".data/logs"
mkdir -p "$LOG_DIR" "$PID_DIR"

# CORS 白名单默认跟随 web 端口（API 端按 Origin 精确匹配）。注意：若复用已在跑的旧 API 进程，
# CORS 以旧进程启动时的值为准。
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:${WEB_PORT}}"

# 等待健康检查，就绪后把 pid/端口记录到 .data/pids/ 供 start.sh stop 精确停止。
ensure_service() {  # $1=名称 $2=端口 $3=日志文件 $4=健康检查 URL；后面是启动命令
  local name="$1" port="$2" log_file="$3" health_url="$4"
  shift 4
  if curl -sf "$health_url" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "$name already running on :$port — reusing it (not managed by start.sh stop)"
    return 0
  fi
  echo "starting $name on :$port ... (log: $log_file)"
  "$@" >>"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_DIR/$name.pid"
  echo "$port" > "$PID_DIR/$name.port"
  local attempt
  for attempt in $(seq 1 60); do
    if curl -sf "$health_url" 2>/dev/null | grep -q '"status":"ok"'; then
      echo "$name is up"
      return 0
    fi
    kill -0 "$pid" 2>/dev/null || { echo "error: $name died during startup — see $log_file" >&2; exit 1; }
    sleep 0.5
  done
  echo "error: $name did not become healthy within 30s — see $log_file" >&2
  exit 1
}

ensure_service "skill" 8321 "$LOG_DIR/skill.log" "$SKILL_URL/health" \
  env PYTHONPATH=packages uv run uvicorn skill.main:app --host 0.0.0.0 --port 8321

ensure_service "api" 8400 "$LOG_DIR/api.log" "$API_URL/health" \
  env PYTHONPATH=packages uv run uvicorn main:app --app-dir apps/api --host 0.0.0.0 --port 8400

# web：next dev 无 /health，首页 200 即视为就绪；首次编译可能几十秒。
if curl -sf "http://localhost:${WEB_PORT}" >/dev/null 2>&1; then
  echo "web already running on :$WEB_PORT — reusing it (not managed by start.sh stop)"
else
  [ -d apps/web/node_modules ] || (cd apps/web && pnpm install)
  echo "starting web frontend on :$WEB_PORT ... (log: $LOG_DIR/web.log)"
  # -p 固定端口，被占即 fail-fast；子 shell 整体后台，日志入文件
  (cd apps/web && NEXT_PUBLIC_API_URL="$API_URL" pnpm dev -p "$WEB_PORT") >>"$LOG_DIR/web.log" 2>&1 &
  echo $! > "$PID_DIR/web.pid"
  echo "$WEB_PORT" > "$PID_DIR/web.port"
  for attempt in $(seq 1 120); do
    if curl -sf "http://localhost:${WEB_PORT}" >/dev/null 2>&1; then
      echo "web is up"
      break
    fi
    kill -0 "$(cat "$PID_DIR/web.pid")" 2>/dev/null || { echo "error: web died during startup — see $LOG_DIR/web.log" >&2; exit 1; }
    sleep 0.5
  done
fi

echo
echo "OpenTalos is up:"
echo "  web    http://localhost:$WEB_PORT"
echo "  api    $API_URL"
echo "  skill  $SKILL_URL"
echo "logs: tail -f $LOG_DIR/{skill,api,web}.log    stop: ./scripts/start.sh stop"
