#!/usr/bin/env bash
# OpenTalos local dev stack manager: worker + api + web + admin (+ postgres).
#
# Status/stop are port-based (lsof), not PID-file-based: whatever process is actually bound to a
# service's port is the thing that gets signaled. This is deliberately stateless across shells —
# no stale PID file can ever point at the wrong (or a since-recycled) process.
#
# worker/api are built before every start, since they run from apps/*/dist — via `turbo run
# build --filter`, not a bare `pnpm --filter <pkg> build`, so a package's own workspace
# dependencies (core-types, chat-agent, a brand-new package, ...) get rebuilt first if their dist
# is stale or missing entirely — otherwise tsc fails against whatever dist happened to already
# exist locally (or doesn't exist at all for a package added since this checkout's last build),
# which looks like a real compile error but is actually just a stale local build cache. Cheap when
# nothing changed (turbo caches every package), necessary when something did.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
# The regular local-dev Postgres — deliberately NOT apps/web/e2e/docker-compose.yml, whose data
# is dropped and reseeded on every Playwright run (see apps/web/e2e/global-setup.ts). Sharing that
# file here once destroyed real tenant/API-key data every time the E2E suite ran.
COMPOSE_FILE="$ROOT_DIR/scripts/docker-compose.postgres.yml"

# Restart/start/stop "all" touches only these — postgres is stateful and managed separately via
# postgres:up/postgres:down, so a routine app restart can never take the database down with it.
APP_SERVICES=(worker api web admin)

mkdir -p "$LOG_DIR"

port_for() {
	case "$1" in
	worker) echo 3002 ;;
	api) echo 3001 ;;
	web) echo 5173 ;;
	admin) echo 5174 ;;
	*)
		echo "unknown service: $1 (expected one of: ${APP_SERVICES[*]})" >&2
		exit 1
		;;
	esac
}

pids_on_port() {
	lsof -ti:"$1" 2>/dev/null || true
}

is_running() {
	[ -n "$(pids_on_port "$(port_for "$1")")" ]
}

build_service() {
	case "$1" in
	worker) (cd "$ROOT_DIR" && pnpm exec turbo run build --filter=@opentalos/worker) ;;
	api) (cd "$ROOT_DIR" && pnpm exec turbo run build --filter=@opentalos/api) ;;
	esac
}

start_service() {
	local name="$1" port
	port=$(port_for "$name")

	if is_running "$name"; then
		echo "[$name] 已在运行 (:$port)"
		return 0
	fi

	case "$name" in
	worker | api)
		echo "[$name] 构建中..."
		if ! build_service "$name"; then
			echo "[$name] 构建失败，未启动" >&2
			return 1
		fi
		echo "[$name] 启动中 (日志: logs/$name.log)"
		(cd "$ROOT_DIR/apps/$name" && nohup node dist/index.js >"$LOG_DIR/$name.log" 2>&1 &)
		;;
	web | admin)
		echo "[$name] 启动中 (日志: logs/$name.log)"
		# --strictPort: 端口被占用时直接报错退出，而不是静默换一个端口——避免脚本以为服务没起来，
		# 实际上只是绑在了别的端口上。
		(cd "$ROOT_DIR/apps/$name" && nohup ./node_modules/.bin/vite --port "$port" --strictPort >"$LOG_DIR/$name.log" 2>&1 &)
		;;
	esac

	for _ in $(seq 1 20); do
		sleep 0.5
		if is_running "$name"; then
			echo "[$name] 已就绪 (:$port)"
			return 0
		fi
	done
	echo "[$name] 启动超时，未监听 :$port —— 查看 logs/$name.log" >&2
	return 1
}

stop_service() {
	local name="$1" port pids
	port=$(port_for "$name")
	pids=$(pids_on_port "$port")

	if [ -z "$pids" ]; then
		echo "[$name] 未在运行"
		return 0
	fi

	echo "[$name] 停止中 (pid: $pids)"
	# shellcheck disable=SC2086
	kill $pids 2>/dev/null
	for _ in $(seq 1 10); do
		sleep 0.3
		[ -z "$(pids_on_port "$port")" ] && return 0
	done
	echo "[$name] 未响应，强制结束"
	# shellcheck disable=SC2086
	kill -9 $(pids_on_port "$port") 2>/dev/null || true
}

postgres_status() {
	if docker compose -f "$COMPOSE_FILE" ps --status running --format '{{.Name}}' 2>/dev/null | grep -q .; then
		echo "up"
	else
		echo "down"
	fi
}

status_all() {
	printf "%-8s %-6s %s\n" 服务 端口 状态
	printf "%-8s %-6s %s\n" postgres 5433 "$(postgres_status)"
	local name port
	for name in "${APP_SERVICES[@]}"; do
		port=$(port_for "$name")
		if is_running "$name"; then
			printf "%-8s %-6s %s\n" "$name" "$port" up
		else
			printf "%-8s %-6s %s\n" "$name" "$port" down
		fi
	done
}

# Only expands "all"/no-args — does NOT validate. Validation lives in validate_services(),
# called directly (not via `$(...)`): bash runs command substitution in a subshell, so an `exit`
# from inside one only kills that subshell — the caller would see an empty expansion and silently
# iterate zero times instead of actually failing. Keeping the two concerns apart avoids that trap.
resolve_targets() {
	if [ "$#" -eq 0 ] || [ "$1" = "all" ]; then
		echo "${APP_SERVICES[@]}"
	else
		echo "$@"
	fi
}

validate_services() {
	local name
	for name in "$@"; do
		port_for "$name" >/dev/null || return 1
	done
}

usage() {
	cat <<USAGE
用法: scripts/dev.sh <command> [service...]

命令:
  start   [service...|all]   启动服务（worker/api 会先构建），不传服务名默认全部
  stop    [service...|all]   停止服务，不传服务名默认全部
  restart [service...|all]   重启服务，不传服务名默认全部
  status                     查看各服务运行状态（含 postgres）
  logs    <service> [-f]     查看日志，-f 持续跟踪
  postgres:up                启动本地 Postgres（docker compose，独立于 start/stop/restart all）
  postgres:down              停止本地 Postgres

服务: ${APP_SERVICES[*]}

示例:
  scripts/dev.sh start               # 启动 worker/api/web/admin
  scripts/dev.sh restart api worker  # 只重启 api 和 worker
  scripts/dev.sh stop web            # 只停掉 web
  scripts/dev.sh status
  scripts/dev.sh logs api -f
  scripts/dev.sh postgres:up         # 首次启动前先起数据库
USAGE
}

main() {
	local cmd="${1:-}"
	[ "$#" -gt 0 ] && shift

	case "$cmd" in
	start | stop | restart)
		validate_services "$@" || exit 1
		local targets
		targets=$(resolve_targets "$@")
		local ok=0
		case "$cmd" in
		start)
			for t in $targets; do start_service "$t" || ok=1; done
			;;
		stop)
			for t in $targets; do stop_service "$t"; done
			;;
		restart)
			for t in $targets; do stop_service "$t"; done
			for t in $targets; do start_service "$t" || ok=1; done
			;;
		esac
		exit "$ok"
		;;
	status)
		status_all
		;;
	logs)
		local name="${1:-}"
		if [ -z "$name" ]; then
			echo "用法: scripts/dev.sh logs <service> [-f]" >&2
			exit 1
		fi
		port_for "$name" >/dev/null || exit 1
		shift || true
		if [ ! -f "$LOG_DIR/$name.log" ]; then
			echo "还没有日志文件：logs/$name.log（服务可能还没启动过）" >&2
			exit 1
		fi
		if [ "${1:-}" = "-f" ]; then
			tail -f "$LOG_DIR/$name.log"
		else
			tail -n 100 "$LOG_DIR/$name.log"
		fi
		;;
	postgres:up)
		docker compose -f "$COMPOSE_FILE" up -d
		;;
	postgres:down)
		docker compose -f "$COMPOSE_FILE" down
		;;
	-h | --help | help | "")
		usage
		;;
	*)
		echo "未知命令: $cmd" >&2
		usage
		exit 1
		;;
	esac
}

main "$@"
