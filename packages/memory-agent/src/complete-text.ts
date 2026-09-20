import type { ModelProvider } from "@opentalos/core-types";

/** 跑一次不带工具调用的模型请求，把所有 text_delta 拼成完整字符串返回。刻意不基于
 * packages/sdk 的 runModelWithTools —— 那是给 graph 节点用 yield* 委托的生成器，带工具调用/HITL/
 * steering 语义；提取/整合这两个"迷你 agent"只是一次性的纯文本请求，没有工具、不在任何 graph
 * 里跑，用一个专门的小函数比硬套一个不匹配的抽象更简单。 */
export async function completeText(provider: ModelProvider, systemPrompt: string, userPrompt: string): Promise<string> {
  let text = "";
  for await (const chunk of provider.complete({
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ],
  })) {
    if (chunk.type === "text_delta") text += chunk.textDelta;
  }
  return text;
}
