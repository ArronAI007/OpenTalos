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
export interface SkillSummary {
  name: string;
  description: string;
  added: boolean;
  tags: string[];
  usage_count: number;
}
export interface SkillsResponse {
  reachable: boolean;
  skills: SkillSummary[];
  error?: string;
}
export interface SkillCandidate { relative_path: string; name: string; description: string }
export interface GithubImportSkipped { name: string; reason: string }
export interface GithubImportResult { imported: string[]; skipped: GithubImportSkipped[] }

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
export async function createTask(): Promise<Task> {
  return fetchJson<RawTask>(`${API_URL}/api/tasks`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
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
export async function deleteTurn(taskId: string, messageId: number): Promise<void> {
  // 删整轮（user 行 + 其后直到下一 user 前的所有行）；204 无响应体，仅校验状态码（同 deleteTask）。
  const res = await fetch(`${API_URL}/api/tasks/${taskId}/messages/${messageId}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText}`);
  }
}
export async function respondToApproval(taskId: string, approvalId: string, approved: boolean): Promise<void> {
  // 副作用工具的审批决定；结果由流内的 approval_resolved 事件回流（这里不本地改状态）。
  const res = await fetch(`${API_URL}/api/tasks/${taskId}/approvals/${approvalId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText}`);
  }
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

// 这两个函数手动读一次非 2xx 响应体里的 detail 展示给用户（400/502 时比通用 fetchJson 的
// "API 状态码 状态文本"更有用），不改 fetchJson 的通用行为，避免影响其他调用点。
async function postJsonWithDetail<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    const detail = data && typeof data.detail === "string" ? data.detail : null;
    throw new Error(detail ?? `请求失败（HTTP ${res.status}）`);
  }
  return res.json() as Promise<T>;
}

export async function scanGithubSkills(repoUrl: string): Promise<SkillCandidate[]> {
  return postJsonWithDetail<{ candidates: SkillCandidate[] }>(`${API_URL}/api/skills/github/scan`, {
    repo_url: repoUrl,
  }).then((d) => d.candidates);
}

export async function importGithubSkills(repoUrl: string, relativePaths: string[]): Promise<GithubImportResult> {
  return postJsonWithDetail<GithubImportResult>(`${API_URL}/api/skills/github/import`, {
    repo_url: repoUrl,
    relative_paths: relativePaths,
  });
}

export async function addMySkill(name: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/my-skills/${encodeURIComponent(name)}`, { method: "POST" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}

export async function removeMySkill(name: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/my-skills/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}

export async function uploadSkill(file: File): Promise<{ name: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_URL}/api/skill-upload`, { method: "POST", body: formData });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    const detail = data && typeof data.detail === "string" ? data.detail : null;
    throw new Error(detail ?? `请求失败（HTTP ${res.status}）`);
  }
  return res.json();
}

export interface SkillFile {
  path: string;
  content: string | null;
}
export interface SkillDetail {
  name: string;
  description: string;
  frontmatter_yaml: string | null;
  tags: string[];
  usage_count: number;
  added: boolean;
  updated_at: string;
  files: SkillFile[];
}

export async function getSkillDetail(name: string): Promise<SkillDetail> {
  return fetchJson<SkillDetail>(`${API_URL}/api/skills/${encodeURIComponent(name)}`, { cache: "no-store" });
}

export async function suggestSkillUsage(name: string, description: string): Promise<string[]> {
  const data = await fetchJson<{ items: string[] }>(
    `${API_URL}/api/skills/${encodeURIComponent(name)}/usage-examples`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ description }) }
  );
  return data.items;
}

export interface EvalCase {
  id: string;
  name: string;
  instruction: string;
  expected_answer: string | null;
}
export interface EvalScore {
  correctness: number;
  completeness: number;
  clarity: number;
  comment: string;
}
export interface EvalResult {
  case_id: string;
  case_name: string;
  agent_type: string;
  reply: string | null;
  score: EvalScore | null;
  error: string | null;
  latency_ms: number;
  tokens_used: number;
}
export interface EvalRun {
  id: string;
  created_at: string;
  results: EvalResult[];
}

export async function listEvalCases(): Promise<EvalCase[]> {
  return fetchJson<{ cases: EvalCase[] }>(`${API_URL}/api/eval/cases`, { cache: "no-store" }).then((d) => d.cases);
}

export async function createEvalCase(
  name: string,
  instruction: string,
  expectedAnswer: string | null
): Promise<EvalCase> {
  return fetchJson<EvalCase>(`${API_URL}/api/eval/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, instruction, expected_answer: expectedAnswer }),
  });
}

export async function deleteEvalCase(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/eval/cases/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}

export async function runEval(caseIds: string[], agentTypes: string[]): Promise<EvalRun> {
  return postJsonWithDetail<EvalRun>(`${API_URL}/api/eval/run`, {
    case_ids: caseIds,
    agent_types: agentTypes,
  });
}

export async function listEvalRuns(): Promise<EvalRun[]> {
  return fetchJson<{ runs: EvalRun[] }>(`${API_URL}/api/eval/runs`, { cache: "no-store" }).then((d) => d.runs);
}

export async function deleteEvalRun(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/eval/runs/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}
