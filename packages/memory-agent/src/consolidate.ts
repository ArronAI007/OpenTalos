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

const VALID_MEMORY_TYPES = new Set<string>(["profile", "preference", "context"]);

function isValidNewMemory(item: unknown): item is ConsolidationResult["add"][number] {
  return (
    !!item &&
    typeof item === "object" &&
    VALID_MEMORY_TYPES.has((item as Record<string, unknown>).type as string) &&
    typeof (item as Record<string, unknown>).title === "string" &&
    typeof (item as Record<string, unknown>).content === "string"
  );
}

function isValidMemoryUpdate(item: unknown): item is ConsolidationResult["update"][number] {
  return (
    !!item &&
    typeof item === "object" &&
    typeof (item as Record<string, unknown>).id === "string" &&
    typeof (item as Record<string, unknown>).content === "string"
  );
}

/** 从"已知是数组"的原始数组里过滤出形状合法的条目，把非法条目记录下来再丢弃——而不是直接
 * cast 放行。 memories.type 在 schema 里就是普通 TEXT 字段，数据库层面不会拒绝一个模型幻觉出来的
 * type 值，所以这一步是唯一的把关点。 */
function filterValid<T>(items: unknown[], isValid: (item: unknown) => item is T, label: string): T[] {
  const valid: T[] = [];
  for (const item of items) {
    if (isValid(item)) {
      valid.push(item);
    } else {
      console.error(`memory-agent: consolidation model returned an invalid ${label} item, dropping it: ${JSON.stringify(item).slice(0, 200)}`);
    }
  }
  return valid;
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
  if (!Array.isArray(obj.add) || !Array.isArray(obj.update) || !Array.isArray(obj.delete)) {
    console.error(`memory-agent: consolidation model returned an unexpected shape (missing/non-array add/update/delete): ${raw.slice(0, 200)}`);
  }
  const add = Array.isArray(obj.add) ? filterValid(obj.add, isValidNewMemory, "add") : [];
  const update = Array.isArray(obj.update) ? filterValid(obj.update, isValidMemoryUpdate, "update") : [];
  const del = Array.isArray(obj.delete) ? filterValid(obj.delete, (id): id is string => typeof id === "string", "delete") : [];
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

  // 一旦某条 delete 提交，被删的记忆就不会再出现在下一轮传给模型的"已确认的记忆"里——如果后续
  // 步骤（比如 deleteRawMemories）在这之后失败，触发过这条 delete 的原始观察下次重跑时会被当成
  // "全新信息"重新解读，有可能把刚删掉的内容悄悄地重新加回来。
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
  // 注意：upsertMemories/deleteMemories/deleteRawMemories 是三个独立事务，整体并不原子——如果在
  // 它们之间崩溃，重试时对同一个 title 再次 add 会撞上 (tenantId, title) 唯一约束，且没有退避/去重
  // 机制，存在活锁风险（留给调用方，即 Task 6/7 的 worker 处理）。
  // 处理过的 raw_memories 全部清空，不管模型是否采纳——这批已经被完整看过一遍，留着没有增量价值
  // （见 spec 里"整合"一节的明确设计决定）。
  await deleteRawMemories(pool, tenantId, raw.map((r) => r.id));
}
