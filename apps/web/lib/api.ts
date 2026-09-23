export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8400";

export interface Task { id: string; title: string; agent_type: string; updated_at: string; pinned: boolean; starred: boolean }

// 后端 SQLite 用 0/1 存 pinned/starred；统一在此处归一为 boolean，组件层只见 boolean。
type RawTask = Omit<Task, "pinned" | "starred"> & { pinned: number; starred: number };
function toTask(raw: RawTask): Task {
  return { ...raw, pinned: Boolean(raw.pinned), starred: Boolean(raw.starred) };
}
export interface StoredMessage { id: number; kind: "user" | "assistant" | "tool"; content: string; created_at: string }
export interface AppConfig { model_name: string | null; agent_types: string[]; skills_reachable: boolean | null }
export interface SkillsResponse { reachable: boolean; skills: { name: string; description: string }[]; error?: string }

async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchConfig(): Promise<AppConfig> {
  return fetchJson<AppConfig>(`${API_URL}/api/config`);
}
export async function listTasks(): Promise<Task[]> {
  return fetchJson<{ tasks: RawTask[] }>(`${API_URL}/api/tasks`, { cache: "no-store" }).then((d) => d.tasks.map(toTask));
}
export async function createTask(agentType: string): Promise<Task> {
  return fetchJson<RawTask>(`${API_URL}/api/tasks`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_type: agentType }),
  }).then(toTask);
}
export async function updateTask(id: string, patch: { title?: string; pinned?: boolean; starred?: boolean }): Promise<Task> {
  return fetchJson<RawTask>(`${API_URL}/api/tasks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  }).then(toTask);
}
export async function deleteTask(id: string): Promise<void> {
  // 204 无响应体，不能走 fetchJson 的 res.json()，仅校验状态码。
  const res = await fetch(`${API_URL}/api/tasks/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText}`);
  }
}
export async function listMessages(taskId: string): Promise<StoredMessage[]> {
  return fetchJson<{ messages: StoredMessage[] }>(`${API_URL}/api/tasks/${taskId}/messages`, { cache: "no-store" }).then((d) => d.messages);
}
export async function listSkills(): Promise<SkillsResponse> {
  return fetchJson<SkillsResponse>(`${API_URL}/api/skills`, { cache: "no-store" });
}
