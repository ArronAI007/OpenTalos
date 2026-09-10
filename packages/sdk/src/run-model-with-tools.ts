import type { Message, ModelProvider, ToolCall, ToolDefinition } from "@opentalos/core-types";
import type { NodeResumeValue, NodeYield } from "@opentalos/core-graph";

export interface AgentTurnResult {
  messages: Message[];
  finalText: string;
}

const DEFAULT_MAX_ROUNDS = 10;

/**
 * Runs a model-completion + tool-call loop, delegatable via `yield*` from inside a graph node.
 * `GraphEngine` auto-resolves every `awaiting_tool` yield through the tool registry (no human
 * step involved — see packages/core-graph/src/engine.ts), so this loop runs every tool round
 * automatically; it is the CALLER's job to add a human-approval gate (`awaiting_approval`) after
 * this returns, if one is wanted. Loops until the model produces a turn with no tool calls at
 * all, or until `maxRounds` completion calls have been made — whichever comes first. The bound
 * exists because nothing else in this codebase currently caps a runaway tool-calling loop (a
 * real, not hypothetical, LLM failure mode): without it, a model stuck repeatedly requesting
 * tools would hold a worker's concurrency slot forever.
 */
export async function* runModelWithTools(
  provider: ModelProvider,
  tools: ToolDefinition[],
  messages: Message[],
  maxRounds: number = DEFAULT_MAX_ROUNDS,
): AsyncGenerator<NodeYield, AgentTurnResult, NodeResumeValue> {
  let conversation = messages;
  for (let round = 0; round < maxRounds; round++) {
    let assistantText = "";
    const pendingToolCalls: ToolCall[] = [];
    for await (const chunk of provider.complete({ messages: conversation, tools })) {
      if (chunk.type === "text_delta") {
        assistantText += chunk.textDelta;
      } else if (chunk.type === "tool_call") {
        pendingToolCalls.push(chunk.toolCall);
      }
    }

    if (pendingToolCalls.length === 0) {
      return { messages: conversation, finalText: assistantText };
    }

    conversation = [...conversation, { role: "assistant", content: assistantText, toolCalls: pendingToolCalls }];
    for (const toolCall of pendingToolCalls) {
      const resume = yield { type: "awaiting_tool", toolCall };
      const result =
        resume?.type === "tool_result" ? resume.result : { id: toolCall.id, output: "no result", isError: true };
      conversation = [...conversation, { role: "tool", content: String(result.output), toolCallId: result.id }];
    }
  }
  throw new Error(
    `runModelWithTools: exceeded maxRounds (${maxRounds}) without the model producing a turn with no tool calls — the model may be stuck in a repetitive tool-calling loop`,
  );
}
