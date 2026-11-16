import type { Task } from "./api";

export function filterConversations(
  tasks: Task[],
  query: string
): Task[] {
  const needle = query.trim().toLowerCase();
  return [...tasks]
    .filter((task) => {
      if (!needle) return true;
      return `${task.title} ${task.agent_name ?? ""} ${task.agent_type}`
        .toLowerCase()
        .includes(needle);
    })
    .sort((left, right) => {
      if (left.pinned !== right.pinned) return left.pinned ? -1 : 1;
      return right.updated_at.localeCompare(left.updated_at);
    });
}

export function conversationTitle(task: Task): string {
  return task.title.trim() || "未命名会话";
}
