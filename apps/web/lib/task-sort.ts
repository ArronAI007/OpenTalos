import type { Task } from "@/lib/api";

// 与服务端 list_tasks 同序：固定任务在前，组内按 updated_at 降序。
// updated_at 为零填充的本地时间字符串（%Y-%m-%dT%H:%M:%S.%f），字典序即时间序。
// 返回新数组，不修改入参。
export function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    if (a.updated_at === b.updated_at) return 0;
    return a.updated_at < b.updated_at ? 1 : -1;
  });
}
