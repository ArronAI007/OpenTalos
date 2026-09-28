const key = (taskId: string) => `opentalos.pending.${taskId}`;

export function stashPendingMessage(taskId: string, content: string): void {
  sessionStorage.setItem(key(taskId), content);
}

export function takePendingMessage(taskId: string): string | null {
  const value = sessionStorage.getItem(key(taskId));
  if (value !== null) sessionStorage.removeItem(key(taskId));
  return value;
}

const HOME_DRAFT_KEY = "opentalos.pending.home-draft";

export function stashHomeDraft(content: string): void {
  try {
    sessionStorage.setItem(HOME_DRAFT_KEY, content);
  } catch {
    // 忽略写入失败（隐私模式/存储禁用等）——预填是锦上添花，不是关键路径。
  }
}

export function takeHomeDraft(): string | null {
  try {
    const value = sessionStorage.getItem(HOME_DRAFT_KEY);
    if (value !== null) sessionStorage.removeItem(HOME_DRAFT_KEY);
    return value;
  } catch {
    return null;
  }
}
