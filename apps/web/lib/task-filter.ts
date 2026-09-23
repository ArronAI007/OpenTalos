import type { Task } from "@/lib/api";

// 按标题做本地过滤：trim + 小写，空 query 原样返回全部（不做后端查询）。
export function filterTasksByTitle(tasks: Task[], query: string): Task[] {
  const q = query.trim().toLowerCase();
  if (q === "") return tasks;
  return tasks.filter((task) => (task.title ?? "").toLowerCase().includes(q));
}
