import type { ModelProvider } from "@opentalos/core-types";
import { insertRawMemory } from "@opentalos/postgres-memory";
import type { Pool } from "pg";
import { completeText } from "./complete-text.js";

const EXTRACTION_SYSTEM_PROMPT = `你是一个记忆提取助手。你会看到一轮用户和 AI 助手之间的对话，任务是判断这段对话里有没有出现值得长期记住的、跨对话仍然成立的用户信息（比如用户的身份背景、对回复方式的偏好、正在进行的长期计划）。

不该提取的内容：
- 单次性、临时性的问答本身（比如"今天几号""汇率多少"），除非其中体现了跨对话仍然成立的用户信息。
- 助手自己算出来的、不是关于用户的事实性输出。
- 用户消息里出现的密钥/密码/token 等敏感信息——发现了就跳过，绝不能输出。

大多数对话都不包含值得记住的信息，这种情况下应该判断为不需要保存，不要为了"总有点什么"而勉强总结。

只输出一个 JSON 对象，不要有任何其他文字：
- 如果没有值得记住的信息：{"shouldSave": false}
- 如果有：{"shouldSave": true, "content": "一句话描述这条信息"}`;

export interface ConversationTurn {
  tenantId: string;
  sessionId: string;
  runId: string;
  userMessage: string;
  assistantReply: string;
}

/** 任何解析失败都当成"不需要保存"处理，而不是抛出异常——一次偶发的格式错误不应该让整个提取
 * 流程报错（这条路径本来就是 fire-and-forget，见 apps/worker 的接入点，Task 6）。 */
function parseExtractionResult(raw: string): { shouldSave: boolean; content?: string } {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && parsed.shouldSave === true && typeof parsed.content === "string") {
      return { shouldSave: true, content: parsed.content };
    }
    return { shouldSave: false };
  } catch {
    return { shouldSave: false };
  }
}

export async function extractMemory(pool: Pool, provider: ModelProvider, turn: ConversationTurn): Promise<void> {
  const userPrompt = `用户：${turn.userMessage}\n助手：${turn.assistantReply}`;
  const raw = await completeText(provider, EXTRACTION_SYSTEM_PROMPT, userPrompt);
  const result = parseExtractionResult(raw);
  if (!result.shouldSave || !result.content) return;
  await insertRawMemory(pool, {
    tenantId: turn.tenantId,
    sessionId: turn.sessionId,
    runId: turn.runId,
    content: result.content,
  });
}
