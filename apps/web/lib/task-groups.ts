import type { Task } from "@/lib/api";

export type TaskGroupKey = "today" | "yesterday" | "earlier";

export interface TaskGroup {
  key: TaskGroupKey;
  label: string;
  tasks: Task[];
}

const GROUP_LABELS: Record<TaskGroupKey, string> = {
  today: "今天",
  yesterday: "昨天",
  earlier: "更早",
};

// 本地时区当天 0 点。
function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function groupKeyOf(date: Date, now: Date): TaskGroupKey {
  const todayStart = startOfDay(now);
  const yesterdayStart = new Date(todayStart.getFullYear(), todayStart.getMonth(), todayStart.getDate() - 1);
  if (date >= todayStart) return "today";
  if (date >= yesterdayStart) return "yesterday";
  return "earlier";
}

// 按本地时区把任务分为今天/昨天/更早三组，只保留非空组，组内保持传入顺序。
export function groupTasksByDate(tasks: Task[], now: Date): TaskGroup[] {
  const buckets: Record<TaskGroupKey, Task[]> = { today: [], yesterday: [], earlier: [] };
  for (const task of tasks) {
    buckets[groupKeyOf(new Date(task.updated_at), now)].push(task);
  }
  return (["today", "yesterday", "earlier"] as const)
    .filter((key) => buckets[key].length > 0)
    .map((key) => ({ key, label: GROUP_LABELS[key], tasks: buckets[key] }));
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// 格式化任务时间：今天 → HH:MM；昨天 → 昨天 HH:MM；更早 → YYYY/M/D。
export function formatTaskTime(date: Date, now: Date): string {
  const hm = `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
  const key = groupKeyOf(date, now);
  if (key === "today") return hm;
  if (key === "yesterday") return `昨天 ${hm}`;
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
}
