const key = (taskId: string) => `opentalos.pending.${taskId}`;

export function stashPendingMessage(taskId: string, content: string): void {
  sessionStorage.setItem(key(taskId), content);
}

export function takePendingMessage(taskId: string): string | null {
  const value = sessionStorage.getItem(key(taskId));
  if (value !== null) sessionStorage.removeItem(key(taskId));
  return value;
}
