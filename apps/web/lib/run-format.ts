import type { RunSummary } from "./runs-api";

export function statusLabel(status: string): string {
  if (status === "completed") return "✓";
  if (status === "failed") return "✗";
  if (status === "running") return "进行中";
  if (status === "cancelled") return "已取消";
  return status;
}

export function formatDuration(
  run: Pick<RunSummary, "status" | "duration_seconds">
): string {
  if (run.status === "running") return "进行中";
  return `${run.duration_seconds.toFixed(1)}s`;
}
