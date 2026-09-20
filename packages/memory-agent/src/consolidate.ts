import type { ModelProvider } from "@opentalos/core-types";
import {
  deleteMemories,
  deleteRawMemories,
  listMemoriesForTenant,
  listRawMemoriesForTenant,
  upsertMemories,
  type MemoryType,
} from "@opentalos/postgres-memory";
import type { Pool } from "pg";
import { completeText } from "./complete-text.js";

const CONSOLIDATION_SYSTEM_PROMPT = `你是一个记忆整合助手。你会看到某个用户"已确认的记忆"列表和一批"待处理的原始观察"，任务是把原始观察合并进已确认的记忆里，输出一组具体操作。

规则：
- 一条原始观察如果是全新信息，输出一个 add 操作。
- 一条原始观察如果是对已有记忆的补充/修正/推翻，输出一个 update（改写这条记忆）或 delete（这条记忆已经不成立了）操作，引用已有记忆的 id。
- 一条原始观察如果跟已有记忆完全重复，不用输出任何操作（忽略即可）。
- profile/preference 类型的记忆一般是稳定的，不要轻易 delete；context 类型的记忆容易过时，看起来不再成立就应该 delete。

只输出一个 JSON 对象，不要有任何其他文字，格式：
{"add": [{"type": "profile"|"preference"|"context", "title": "...", "content": "..."}], "update": [{"id": "...", "content": "..."}], "delete": ["id1", "id2"]}
如果没有任何要做的操作，输出 {"add": [], "update": [], "delete": []}`;

interface ConsolidationResult {
  add: { type: MemoryType; title: string; content: string }[];
  update: { id: string; content: string }[];
  delete: string[];
}

/** 任何解析失败都当成"这次什么都不做"，而不是抛出异常——原始观察本身不会丢（还留在
 * raw_memories 里，见下面的写回逻辑：只有真正跑完一次整合，处理过的原始观察才会被清空），下一
 * 次整合周期会重新尝试。跟 extraction.ts 的 parseExtractionResult 一样，区分"模型合法地说无操作"
 * 和"模型输出解析失败/形状不对"两种情况并分别记录日志，方便排查持续性的 prompt 问题。 */
function parseConsolidationResult(raw: string): ConsolidationResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    console.error(`memory-agent: consolidation model returned non-JSON output: ${raw.slice(0, 200)}`);
    return { add: [], update: [], delete: [] };
  }
  if (!parsed || typeof parsed !== "object") {
    console.error(`memory-agent: consolidation model returned a non-object JSON value: ${raw.slice(0, 200)}`);
    return { add: [], update: [], delete: [] };
  }
  const obj = parsed as Record<string, unknown>;
  const add = Array.isArray(obj.add) ? (obj.add as ConsolidationResult["add"]) : [];
  const update = Array.isArray(obj.update) ? (obj.update as ConsolidationResult["update"]) : [];
  const del = Array.isArray(obj.delete) ? (obj.delete as ConsolidationResult["delete"]) : [];
  if (!Array.isArray(obj.add) || !Array.isArray(obj.update) || !Array.isArray(obj.delete)) {
    console.error(`memory-agent: consolidation model returned an unexpected shape (missing/non-array add/update/delete): ${raw.slice(0, 200)}`);
  }
  return { add, update, delete: del };
}

export async function consolidateMemoriesForTenant(
  pool: Pool,
  provider: ModelProvider,
  tenantId: string,
  options?: { signal?: AbortSignal },
): Promise<void> {
  const [existing, raw] = await Promise.all([listMemoriesForTenant(pool, tenantId), listRawMemoriesForTenant(pool, tenantId)]);
  if (raw.length === 0) return;

  const userPrompt =
    `已确认的记忆：\n${existing.map((m) => `- [${m.id}] [${m.type}] ${m.title}: ${m.content}`).join("\n") || "（无）"}\n\n` +
    `待处理的原始观察：\n${raw.map((r) => `- ${r.content}`).join("\n")}`;
  const rawResult = await completeText(provider, CONSOLIDATION_SYSTEM_PROMPT, userPrompt, options);
  const result = parseConsolidationResult(rawResult);

  if (result.add.length > 0 || result.update.length > 0) {
    await upsertMemories(pool, tenantId, { newEntries: result.add, updates: result.update });
  }
  if (result.delete.length > 0) {
    await deleteMemories(pool, tenantId, result.delete);
  }
  // 处理过的 raw_memories 全部清空，不管模型是否采纳——这批已经被完整看过一遍，留着没有增量价值
  // （见 spec 里"整合"一节的明确设计决定）。
  await deleteRawMemories(pool, tenantId, raw.map((r) => r.id));
}
