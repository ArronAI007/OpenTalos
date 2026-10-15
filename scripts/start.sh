#!/usr/bin/env bash
#
# OpenTalos 一键管理（后台模式）：聊天 API + AgentRL 服务 + A2A peer 服务 + Web 前端。
# （技能已进程内化：直接读仓库 skills/ 目录，不再有独立的 skill 服务）
#
#   ./scripts/start.sh          拉起到后台（日志 .data/logs/，pid 记录 .data/pids/），
#                               全部健康后打印地址并退出，终端立即归还
#   ./scripts/start.sh stop     停止本脚本拉起的进程（复用的外部进程不动）
#   ./scripts/start.sh restart  先停后起，等价于 stop + start
#   tail -f .data/logs/web.log  查看某一路日志
#
# 通用性设计（跨机器 / 跨平台 / 慢机器都尽量能跑）：
#   - 依赖安装与进程启动分离：先 `uv sync`（慢，一次性），再用 `uv run --no-sync` 起服务（快）。
#     这样首次安装、需要编译、网络慢等情况不会把耗时耗进健康检查窗口，避免“没在 30s 内变健康”的误报。
#   - 端口、超时、是否自动同步全部可用环境变量覆盖（见下方“可调参数”），默认值适配常见本地开发。
#   - 健康检查兼容 {"status":"ok"} 的空格/格式差异；失败时打印日志尾部，并回收本次拉起的进程，不留僵尸。
#   - 只动 .data/pids/ 里记录的进程与端口：已在跑且健康的服务会被复用，且不归本脚本 stop 管理。
#   - agentrl 是独立 uv 项目（agentrl/pyproject.toml，重型 ML 依赖）：默认纳入启动流程，
#     先 `uv sync --directory agentrl` 再拉起。但它有平台限制（torch 无 macOS x86_64 wheel），
#     装不上/起不来时只警告并跳过，不拖垮其余服务。设 SKIP_AGENTRL=1 可整体跳过。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# ---------------------------------------------------------------------------
# 可调参数（全部可用环境变量覆盖）
# ---------------------------------------------------------------------------
WEB_PORT="${WEB_PORT:-${PORT:-3010}}"     # 兼容旧的 PORT 变量
API_PORT="${API_PORT:-8400}"
AGENTRL_PORT="${AGENTRL_PORT:-8420}"
A2APEER_PORT="${A2APEER_PORT:-8430}"
DEEPRESEARCH_PORT="${DEEPRESEARCH_PORT:-8441}"
HOST="${HOST:-0.0.0.0}"

HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"          # 后端服务健康检查窗口（秒）
WEB_HEALTH_TIMEOUT="${WEB_HEALTH_TIMEOUT:-240}" # web 首次编译可能较慢，单独给更宽裕的窗口
SYNC_TIMEOUT="${SYNC_TIMEOUT:-1800}"            # 依赖/前端安装兜底超时（秒），0 表示不限时
AUTO_SYNC="${AUTO_SYNC:-1}"                     # 启动前是否自动 `uv sync`（0 关闭）
AUTO_SYNC_AGENTRL="${AUTO_SYNC_AGENTRL:-1}"     # agentrl 依赖很重（torch 等），默认自动 sync 以保证服务能起来
SKIP_AGENTRL="${SKIP_AGENTRL:-0}"               # 设为 1 时完全跳过 agentrl（不 sync、不启动）
AUTO_SYNC_DEEPRESEARCH="${AUTO_SYNC_DEEPRESEARCH:-1}"  # 和 agentrl 同款约定，deepresearch 依赖较轻但仍默认自动 sync
SKIP_DEEPRESEARCH="${SKIP_DEEPRESEARCH:-0}"     # 设为 1 时完全跳过 deepresearch（不 sync、不启动）
SKIP_WEB="${SKIP_WEB:-0}"                       # 设为 1 时只起后端服务，跳过 web 前端（CI/无头场景）
WEB_PREWARM="${WEB_PREWARM:-1}"                 # dev 下后台预热各页面路由，避免侧栏首次切换时当场编译卡顿
LOG_TAIL_LINES="${LOG_TAIL_LINES:-30}"          # 失败时回显日志尾部的行数

API_URL="http://localhost:${API_PORT}"
AGENTRL_URL="http://localhost:${AGENTRL_PORT}"
A2APEER_URL="http://localhost:${A2APEER_PORT}"
DEEPRESEARCH_URL="http://localhost:${DEEPRESEARCH_PORT}"
WEB_URL="http://localhost:${WEB_PORT}"

LOG_DIR=".data/logs"
PID_DIR=".data/pids"
MAX_LOG_BYTES=$((10 * 1024 * 1024))
AGENTRL_UP=1
DEEPRESEARCH_UP=1

# CORS 白名单默认跟随 web 端口（API 端按 Origin 精确匹配）。注意：若复用已在跑的旧 API 进程，
# CORS 以旧进程启动时的值为准。
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:${WEB_PORT}}"

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }
die() { echo "error: $*" >&2; exit 1; }

log_tail() {
  local f="$1"
  if [ -f "$f" ]; then
    echo "----- last ${LOG_TAIL_LINES} lines of ${f} -----" >&2
    tail -n "${LOG_TAIL_LINES}" "$f" >&2 || true
    echo "------------------------------------------------" >&2
  fi
}

# 单个日志文件上限：超过则在启动该服务前轮转一份（保留 .1），避免长期运行无限增长。
rotate_log() {
  local f="$1" size
  [ -f "$f" ] || return 0
  size="$(wc -c <"$f" 2>/dev/null || echo 0)"
  if [ "$size" -ge "$MAX_LOG_BYTES" ]; then
    mv -f "$f" "$f.1"
  fi
}

# 该端口上的监听者 PID（没有 lsof 就返回空，退化为只依赖 pid 文件）。
port_listener() {
  have lsof || return 0
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1 || true
}

# 递归结束进程树（uv/pnpm 是包装进程，实际监听者常是孙进程）。
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

# 带兜底超时地前台执行命令；secs<=0 表示不限时。macOS 默认没有 `timeout`，所以自己看门狗。
run_with_timeout() {
  local secs="$1"; shift
  if [ "${secs:-0}" -le 0 ] 2>/dev/null; then
    "$@"; return $?
  fi
  "$@" &
  local pid=$! wd rc=0
  # 看门狗：stdio 全部丢弃（避免继承/占用调用者的 stdout 管道），退出时按进程树整体回收
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null ) >/dev/null 2>&1 &
  wd=$!
  wait "$pid" || rc=$?
  kill_tree "$wd"
  wait "$wd" 2>/dev/null || true
  return "$rc"
}

# 健康检查：兼容 JSON 里的空格/换行差异。先把响应收进变量再 grep，避免 pipefail + grep -q 提前退出误判。
healthy_status() {
  local body
  body="$(curl -fsS --max-time 3 "$1" 2>/dev/null)" || return 1
  printf '%s' "$body" | grep -qE '"status"[[:space:]]*:[[:space:]]*"ok"'
}

# 任意 2xx/3xx 即视为就绪（web 首页用）。
healthy_http() {
  curl -fsS --max-time 3 -o /dev/null "$1" 2>/dev/null
}

# 等待健康；返回非零表示启动失败（已打印日志尾部）。
wait_healthy() {  # name pid url check log_file timeout
  local name="$1" pid="$2" url="$3" check="$4" log_file="$5" timeout="$6"
  local tries=$(( timeout * 2 )) i
  for i in $(seq 1 "$tries"); do
    if "$check" "$url"; then
      echo "$name is up"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "error: $name exited during startup — see $log_file" >&2
      log_tail "$log_file"
      return 1
    fi
    sleep 0.5
  done
  echo "error: $name did not become healthy within ${timeout}s — see $log_file" >&2
  log_tail "$log_file"
  return 1
}

# 拉起一个后端服务并等待健康；健康则把 pid/端口写入 .data/pids/ 供 stop 精确停止。
# fatal=1（默认）时任何启动失败都硬退出；fatal=0 时失败只返回非零（调用方自行降级）。
ensure_service() {  # name port url check log_file fatal cmd...
  local name="$1" port="$2" url="$3" check="$4" log_file="$5" fatal="${6:-1}"
  shift 6
  mkdir -p "$PID_DIR" "$LOG_DIR"

  if "$check" "$url"; then
    echo "$name already running on :$port — reusing it (not managed by start.sh stop)"
    return 0
  fi
  local busy
  busy="$(port_listener "$port")"
  if [ -n "$busy" ]; then
    if [ "$fatal" = "1" ]; then
      die "port $port is held by pid $busy but it did not pass the health check ($url)"
    fi
    echo "warning: port $port is held by pid $busy but it did not pass the health check ($url) — skipping $name" >&2
    return 1
  fi

  rotate_log "$log_file"
  echo "starting $name on :$port ... (log: $log_file)"
  "$@" >>"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" >"$PID_DIR/$name.pid"
  echo "$port" >"$PID_DIR/$name.port"
  if ! wait_healthy "$name" "$pid" "$url" "$check" "$log_file" "$HEALTH_TIMEOUT"; then
    kill_tree "$pid"
    rm -f "$PID_DIR/$name.pid" "$PID_DIR/$name.port"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# 停止
# ---------------------------------------------------------------------------
do_stop() {
  mkdir -p "$PID_DIR"
  local stopped="" pid_file name pid port port_pid killed
  for pid_file in "$PID_DIR"/*.pid; do
    [ -e "$pid_file" ] || break  # 无匹配时 glob 原样保留，直接退出循环
    name="$(basename "$pid_file" .pid)"
    killed=""
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill_tree "$pid"
      killed="$name"
    fi
    # 顶层命令是 uv/pnpm 包装，实际监听者可能是孙进程、pid 那一杀漏网：按记录的端口补杀
    port="$(cat "$PID_DIR/$name.port" 2>/dev/null || true)"
    if [ -n "$port" ]; then
      port_pid="$(port_listener "$port")"
      if [ -n "$port_pid" ]; then
        kill_tree "$port_pid"
        killed="$name"
      fi
    fi
    if [ -n "$killed" ]; then
      stopped="$stopped $name"
    fi
    rm -f "$pid_file" "$PID_DIR/$name.port"
  done
  if [ -n "$stopped" ]; then
    echo "stopped:$stopped"
  else
    echo "nothing to stop (no records in $PID_DIR)"
  fi
}

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
ACTION="${1:-start}"
case "$ACTION" in
  start | stop | restart) ;;
  *)
    echo "usage: $0 [start|stop|restart]" >&2
    exit 2
    ;;
esac

if [ "$ACTION" != "start" ]; then
  do_stop
  [ "$ACTION" = "stop" ] && exit 0
fi

have uv || die "uv is required (https://docs.astral.sh/uv/)"
have curl || die "curl is required"
have lsof || echo "warning: lsof not found — stop will rely on pid files only" >&2

# 依赖同步（慢，一次性）：放在健康检查之前，避免首次安装/编译把启动窗口耗光。
if [ "$AUTO_SYNC" = "1" ]; then
  echo "syncing python dependencies (uv sync) ..."
  if ! run_with_timeout "$SYNC_TIMEOUT" uv sync; then
    die "uv sync failed (or timed out after ${SYNC_TIMEOUT}s). Fix the dependencies, or set AUTO_SYNC=0 to skip."
  fi
  [ -d .venv ] || die "uv sync finished but .venv is missing"
else
  echo "AUTO_SYNC=0 — skipping 'uv sync'"
fi

# agentrl 是独立 uv 项目（自带 pyproject.toml/.venv），依赖很重（torch/transformers/trl…），
# 不在根项目 uv sync 范围内。这里单独 sync，保证 start.sh 能把所有服务都拉起来。
AGENTRL_ENABLED=1
AGENTRL_UNSUPPORTED=0   # sync 失败（多半是平台无 torch wheel）时置 1，经 NEXT_PUBLIC_* 告知前端
if [ "$SKIP_AGENTRL" = "1" ]; then
  echo "SKIP_AGENTRL=1 — skipping agentrl"
  AGENTRL_ENABLED=0
elif [ ! -f agentrl/pyproject.toml ]; then
  echo "warning: agentrl project not found at agentrl/ — skipping agentrl" >&2
  AGENTRL_ENABLED=0
elif [ "$AUTO_SYNC_AGENTRL" = "1" ]; then
  echo "syncing agentrl dependencies (uv sync --directory agentrl; heavy, one-time) ..."
  # agentrl 依赖有平台限制（torch 只发 Linux / macOS arm64 / Windows 的 wheel）。
  # 装不上时只警告并跳过它，不让整个 start.sh 陪葬。
  if ! run_with_timeout "$SYNC_TIMEOUT" uv sync --directory agentrl; then
    echo "warning: agentrl dependencies are unavailable on this platform — skipping agentrl." >&2
    echo "         (torch ships no macOS x86_64 wheel; use Linux / Apple Silicon, or Docker. Set SKIP_AGENTRL=1 to silence.)" >&2
    AGENTRL_ENABLED=0
    AGENTRL_UNSUPPORTED=1
  fi
elif [ ! -d agentrl/.venv ]; then
  echo "warning: AUTO_SYNC_AGENTRL=0 but agentrl/.venv is missing — skipping agentrl" >&2
  AGENTRL_ENABLED=0
fi

# deepresearch 同样是独立 uv 项目（自带 pyproject.toml/.venv），但依赖较轻（没有 agentrl 那种
# 平台受限的重型 ML 依赖），不需要 AGENTRL_UNSUPPORTED 那种"装不上就告知前端降级"的机制——装
# 不上直接警告跳过即可。
DEEPRESEARCH_ENABLED=1
if [ "$SKIP_DEEPRESEARCH" = "1" ]; then
  echo "SKIP_DEEPRESEARCH=1 — skipping deepresearch"
  DEEPRESEARCH_ENABLED=0
elif [ ! -f deepresearch/pyproject.toml ]; then
  echo "warning: deepresearch project not found at deepresearch/ — skipping deepresearch" >&2
  DEEPRESEARCH_ENABLED=0
elif [ "$AUTO_SYNC_DEEPRESEARCH" = "1" ]; then
  echo "syncing deepresearch dependencies (uv sync --directory deepresearch) ..."
  if ! run_with_timeout "$SYNC_TIMEOUT" uv sync --directory deepresearch; then
    echo "warning: deepresearch dependencies failed to install — skipping deepresearch." >&2
    DEEPRESEARCH_ENABLED=0
  fi
elif [ ! -d deepresearch/.venv ]; then
  echo "warning: AUTO_SYNC_DEEPRESEARCH=0 but deepresearch/.venv is missing — skipping deepresearch" >&2
  DEEPRESEARCH_ENABLED=0
fi

ensure_service "api" "$API_PORT" "$API_URL/health" healthy_status "$LOG_DIR/api.log" 1 \
  env PYTHONPATH=packages uv run --no-sync uvicorn main:app --app-dir apps/api --host "$HOST" --port "$API_PORT"

if [ "$AGENTRL_ENABLED" = "1" ]; then
  # agentrl 启动失败也只降级（AGENTRL_UP=0），不影响 api/a2apeer/web。
  ensure_service "agentrl" "$AGENTRL_PORT" "$AGENTRL_URL/health" healthy_status "$LOG_DIR/agentrl.log" 0 \
    uv run --no-sync --directory agentrl uvicorn main:app --host "$HOST" --port "$AGENTRL_PORT" \
    || AGENTRL_UP=0
else
  AGENTRL_UP=0
fi

ensure_service "a2apeer" "$A2APEER_PORT" "$A2APEER_URL/health" healthy_status "$LOG_DIR/a2apeer.log" 1 \
  env PYTHONPATH=packages uv run --no-sync uvicorn a2apeer.main:app --host "$HOST" --port "$A2APEER_PORT"

if [ "$DEEPRESEARCH_ENABLED" = "1" ]; then
  # deepresearch 启动失败也只降级（DEEPRESEARCH_UP=0），不影响其余服务。
  ensure_service "deepresearch" "$DEEPRESEARCH_PORT" "$DEEPRESEARCH_URL/health" healthy_status "$LOG_DIR/deepresearch.log" 0 \
    uv run --no-sync --directory deepresearch uvicorn main:app --host "$HOST" --port "$DEEPRESEARCH_PORT" \
    || DEEPRESEARCH_UP=0
else
  DEEPRESEARCH_UP=0
fi

# web：next dev 无 /health，首页可访问即视为就绪；首次编译可能几十秒。
if [ "$SKIP_WEB" = "1" ]; then
  echo "SKIP_WEB=1 — skipping web frontend"
elif healthy_http "$WEB_URL"; then
  echo "web already running on :$WEB_PORT — reusing it (not managed by start.sh stop)"
else
  have pnpm || die "pnpm is required to run the web frontend"
  # 用 next 可执行文件判断依赖是否真的装完（被中断的 node_modules 目录会存在但不完整）
  if [ ! -x apps/web/node_modules/.bin/next ]; then
    echo "installing web dependencies (pnpm install) ..."
    run_with_timeout "$SYNC_TIMEOUT" pnpm -C apps/web install \
      || die "pnpm install failed (or timed out after ${SYNC_TIMEOUT}s)"
  fi
  web_busy="$(port_listener "$WEB_PORT")"
  if [ -n "$web_busy" ]; then
    die "port $WEB_PORT is held by pid $web_busy"
  fi
  rotate_log "$LOG_DIR/web.log"
  echo "starting web frontend on :$WEB_PORT ... (log: $LOG_DIR/web.log)"
  # -p 固定端口，被占即 fail-fast；子 shell 整体后台，日志入文件
  (
    cd apps/web
    NEXT_PUBLIC_API_URL="$API_URL" NEXT_PUBLIC_AGENTRL_URL="$AGENTRL_URL" \
    NEXT_PUBLIC_AGENTRL_UNSUPPORTED="$AGENTRL_UNSUPPORTED" \
    NEXT_PUBLIC_DEEPRESEARCH_URL="$DEEPRESEARCH_URL" \
      pnpm dev -p "$WEB_PORT"
  ) >>"$LOG_DIR/web.log" 2>&1 &
  web_pid=$!
  echo "$web_pid" >"$PID_DIR/web.pid"
  echo "$WEB_PORT" >"$PID_DIR/web.port"
  if ! wait_healthy "web" "$web_pid" "$WEB_URL" healthy_http "$LOG_DIR/web.log" "$WEB_HEALTH_TIMEOUT"; then
    kill_tree "$web_pid"
    rm -f "$PID_DIR/web.pid" "$PID_DIR/web.port"
    exit 1
  fi
fi

# next dev 按需编译：每个页面路由首次被请求才编译（可长达数秒），侧栏第一次点会明显卡顿。
# web 就绪后在后台把已知路由各请求一遍触发预编译；纯热身，失败不影响任何服务。
if [ "$SKIP_WEB" != "1" ] && [ "$WEB_PREWARM" = "1" ]; then
  echo "prewarming web routes in the background (dev compile) ..."
  (
    for route in "" agents skills eval agentrl deepresearch mcp; do
      curl -fsS --max-time 120 -o /dev/null "$WEB_URL/${route}" 2>/dev/null || true
    done
  ) >>"$LOG_DIR/web.log" 2>&1 &
fi

echo
echo "OpenTalos is up:"
if [ "$SKIP_WEB" = "1" ]; then
  echo "  web      (skipped: SKIP_WEB=1)"
else
  echo "  web      http://localhost:$WEB_PORT"
fi
echo "  api      $API_URL"
if [ "$AGENTRL_UP" = "1" ]; then
  echo "  agentrl  $AGENTRL_URL"
else
  echo "  agentrl  (skipped)"
fi
echo "  a2apeer  $A2APEER_URL"
if [ "$DEEPRESEARCH_UP" = "1" ]; then
  echo "  deepresearch  $DEEPRESEARCH_URL"
else
  echo "  deepresearch  (skipped)"
fi
echo "  skills   in-process (repo ./skills, no separate service)"
echo "logs: tail -f $LOG_DIR/{api,agentrl,a2apeer,deepresearch,web}.log    stop: ./scripts/start.sh stop"
