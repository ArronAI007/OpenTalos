import type { MemoryRecord, MemoryStore, TenantContext } from "@opentalos/core-types";

export interface MemorySummaryEntry {
  type: string;
  title: string;
}

export interface ConversationTurn {
  tenantId: string;
  sessionId: string;
  runId: string;
  userMessage: string;
  assistantReply: string;
}

const DEFAULT_TIMEOUT_MS = 5000;

function memoryServiceUrl(): string {
  return process.env.MEMORY_SERVICE_URL ?? "http://localhost:8001";
}

/** 每次调用都加超时，失败（网络问题/超时/非 2xx）一律抛错——错误要不要被吞掉、只记日志，由各
 * 个调用方自己决定。这跟原来 in-process 调用 packages/memory-agent 里的函数会抛错、由调用方决定
 * 怎么处理是同一个责任划分，只是把"进程内函数调用"换成了"HTTP 调用"，调用方原有的 try/catch
 * 结构不用变（见 apps/worker/src/index.ts 的 onRunDone/runMemoryConsolidationSweep，以及
 * packages/chat-agent/src/graph.ts 的 buildRespondNode——三处调用方原有的错误处理完全不用改）。*/
async function callMemoryService(path: string, init: RequestInit): Promise<Response> {
  const response = await fetch(`${memoryServiceUrl()}${path}`, {
    ...init,
    signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`memory-service ${path} returned HTTP ${response.status}`);
  }
  return response;
}

export async function extractMemory(turn: ConversationTurn): Promise<void> {
  await callMemoryService("/memory/extract", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      tenant_id: turn.tenantId,
      session_id: turn.sessionId,
      run_id: turn.runId,
      user_message: turn.userMessage,
      assistant_reply: turn.assistantReply,
    }),
  });
}

export async function consolidateTenant(tenantId: string): Promise<void> {
  await callMemoryService("/memory/consolidate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId }),
  });
}

export async function listTenantsWithPendingMemories(tenantIds: string[]): Promise<string[]> {
  if (tenantIds.length === 0) return [];
  const response = await callMemoryService(
    `/memory/tenants-with-pending?tenant_ids=${encodeURIComponent(tenantIds.join(","))}`,
    { method: "GET" },
  );
  const body = (await response.json()) as { tenant_ids: string[] };
  return body.tenant_ids;
}

export async function listMemorySummary(tenantId: string): Promise<MemorySummaryEntry[]> {
  const response = await callMemoryService(`/memory/summary?tenant_id=${encodeURIComponent(tenantId)}`, {
    method: "GET",
  });
  const body = (await response.json()) as { entries: MemorySummaryEntry[] };
  return body.entries;
}

/** 实现 core-types 的 MemoryStore 接口，只给 chat-agent 的 search_memory 工具用（见
 * packages/chat-agent/src/tools.ts 的 createSearchMemoryTool）。read/write 在这个仓库里从来没有
 * 真实调用方——跟被这次迁移替换掉的 PostgresMemoryStore 一样，只是为了满足接口契约而存在，没有
 * 对应的 memory-service 端点，调用即抛错。 */
export class HttpMemoryStore implements MemoryStore {
  async read(_key: string, _ctx: TenantContext): Promise<unknown | undefined> {
    throw new Error("HttpMemoryStore.read is not implemented — no memory-service endpoint backs it (unused in this codebase)");
  }

  async write(_key: string, _value: unknown, _ctx: TenantContext): Promise<void> {
    throw new Error("HttpMemoryStore.write is not implemented — no memory-service endpoint backs it (unused in this codebase)");
  }

  async search(query: string, ctx: TenantContext): Promise<MemoryRecord[]> {
    const response = await callMemoryService("/memory/search", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ tenant_id: ctx.tenantId, query }),
    });
    const body = (await response.json()) as { results: MemoryRecord[] };
    return body.results;
  }
}
