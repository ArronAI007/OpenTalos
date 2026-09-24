export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8400";

export interface Task { id: string; title: string; agent_type: string; updated_at: string; pinned: boolean; starred: boolean; archived: boolean; project_id: string | null }

// 后端 SQLite 用 0/1 存 pinned/starred/archived；统一在此处归一为 boolean，组件层只见 boolean。
// project_id 两端同为 string | null，无需转换，随 Omit 直通。
type RawTask = Omit<Task, "pinned" | "starred" | "archived"> & { pinned: number; starred: number; archived: number };
function toTask(raw: RawTask): Task {
  return { ...raw, pinned: Boolean(raw.pinned), starred: Boolean(raw.starred), archived: Boolean(raw.archived) };
}

// PATCH /api/tasks/{id} 的字段集合，至少给一个（后端全空返回 422）。
// project_id 显式传 null 表示移出项目（后端按 model_fields_set 区分"未传入"与"显式 null"）。
export interface TaskPatch { title?: string; pinned?: boolean; starred?: boolean; archived?: boolean; project_id?: string | null }
export interface Project { id: string; name: string; created_at: string }
export interface StoredMessage { id: number; kind: "user" | "assistant" | "tool" | "stopped"; content: string; created_at: string }
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
// 任务列表 URL 拼接：纯函数以便单测。archived=true 拉归档列表，其余情况走主列表（无 query）。
export function tasksUrl(options?: { archived?: boolean }): string {
  return `${API_URL}/api/tasks${options?.archived ? "?archived=1" : ""}`;
}
export async function listTasks(options?: { archived?: boolean }): Promise<Task[]> {
  return fetchJson<{ tasks: RawTask[] }>(tasksUrl(options), { cache: "no-store" }).then((d) => d.tasks.map(toTask));
}
export async function createTask(agentType: string): Promise<Task> {
  return fetchJson<RawTask>(`${API_URL}/api/tasks`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_type: agentType }),
  }).then(toTask);
}
export async function updateTask(id: string, patch: TaskPatch): Promise<Task> {
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
export async function listProjects(): Promise<Project[]> {
  return fetchJson<{ projects: Project[] }>(`${API_URL}/api/projects`, { cache: "no-store" }).then((d) => d.projects);
}
export async function createProject(name: string): Promise<Project> {
  return fetchJson<Project>(`${API_URL}/api/projects`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}
export async function listSkills(): Promise<SkillsResponse> {
  return fetchJson<SkillsResponse>(`${API_URL}/api/skills`, { cache: "no-store" });
}
