#!/usr/bin/env bash
#
# 停止 start.sh 拉起的 OpenTalos 进程：只动 .data/pids/ 里记录的 PID 与端口。
# start.sh 复用的外部进程（非本脚本拉起）没有记录，天然不受影响。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PID_DIR=".data/pids"

stopped=""
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
