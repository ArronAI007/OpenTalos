import type { Message, ModelProvider, ToolCall, ToolDefinition } from "@opentalos/core-types";
import type { NodeResumeValue, NodeYield, SteerChannel } from "@opentalos/core-graph";

export interface AgentTurnResult {
  messages: Message[];
  finalText: string;
  /** The model's full reasoning/thinking trace for this turn, concatenated across every
   * tool-calling round (not just the final one) — empty string for providers/models that don't
   * emit `reasoning_delta` chunks at all. */
  reasoningText: string;
}

const DEFAULT_MAX_ROUNDS = 10;

/** Wraps a steering instruction the same way for every splice site, so the model can reliably
 * tell "the user redirected me mid-reply" apart from an ordinary new conversational turn. */
function frameSteerMessage(message: string): string {
  return `（用户在你刚才的回答过程中补充了新的指示，请据此调整）：${message}`;
}

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
 *
 * `steer` (optional): when provided, a steering instruction delivered while THIS round's model
 * call is still streaming interrupts only that call (never `signal`, the real-cancel path) and
 * splices the partial reply + the instruction into `conversation` before starting a fresh round.
 * A steer delivered between rounds (e.g. during tool execution) is picked up the next time this
 * round loop starts waiting again, with no special-casing needed — see runModelWithTools.test.ts.
 */
export async function* runModelWithTools(
  provider: ModelProvider,
  tools: ToolDefinition[],
  messages: Message[],
  maxRounds: number = DEFAULT_MAX_ROUNDS,
  signal?: AbortSignal,
  steer?: SteerChannel,
): AsyncGenerator<NodeYield, AgentTurnResult, NodeResumeValue> {
  let conversation = messages;
  // Accumulated across ALL rounds (never reset per-round, unlike assistantText below) — the
  // model's reasoning about which tool to call is as much a part of "the agent's thinking
  // process" as its reasoning about the final answer's wording.
  let reasoningText = "";
  for (let round = 0; round < maxRounds; round++) {
    let assistantText = "";
    const pendingToolCalls: ToolCall[] = [];
    yield { type: "emit", eventType: "llm_call_start" };

    // A steer controller scoped to THIS round only, never reused across rounds and never the same
    // object as `signal` (real cancel). AbortSignals are one-shot: reusing one across rounds would
    // permanently prevent every subsequent round's model call from ever starting again once
    // steering fired once. Combined with `signal` (if present) so either one can interrupt the
    // in-flight HTTP call; recomputed fresh every round so a steer-triggered abort this round has
    // zero effect on next round's (brand new) combined signal.
    const roundSteerController = steer ? new AbortController() : undefined;
    const combinedSignal =
      signal && roundSteerController
        ? AbortSignal.any([signal, roundSteerController.signal])
        : (roundSteerController?.signal ?? signal);

    let steeredMessage: string | undefined;
    try {
      const providerIterator = provider
        .complete({ messages: conversation, tools }, { signal: combinedSignal })
        [Symbol.asyncIterator]();
      // A promise that never settles, used as the "no steer channel provided" side of the race
      // below so Promise.race always has exactly two real contenders when steer is undefined too.
      const neverSteers = new Promise<never>(() => {});
      // Subscribed exactly ONCE per round, then raced against every chunk that arrives during
      // this round — NOT re-subscribed per chunk. `waitForNext()` hands back a single promise for
      // "the next steer message, whenever it arrives"; calling it again before that promise
      // settles would abandon the original subscription (any channel implementation that resolves
      // a fresh promise per call, like the test double here, would silently drop a steer delivered
      // in the gap between two chunks — see runModelWithTools.test.ts's steering test, which hangs
      // if this is re-subscribed inside the loop below).
      const steerPromise = (steer?.waitForNext() ?? neverSteers).then((message) => ({
        kind: "steer" as const,
        message,
      }));
      while (true) {
        // Kept as a named reference (not inlined into Promise.race's array) so the LOSING one can
        // be explicitly silenced below: Promise.race never cancels its losing input, so when steer
        // wins, the still-pending chunk fetch eventually settles on its own — usually rejecting,
        // since `roundSteerController.abort()` (below) is what makes it settle at all. Without a
        // .catch() on that specific abandoned promise, that later rejection is unobserved by
        // anything and surfaces as an unhandled promise rejection.
        const chunkPromise = providerIterator.next().then((result) => ({ kind: "chunk" as const, result }));
        const winner = await Promise.race([chunkPromise, steerPromise]);
        if (winner.kind === "steer") {
          steeredMessage = winner.message;
          roundSteerController?.abort();
          chunkPromise.catch(() => {});
          break;
        }
        if (winner.result.done) break;
        const chunk = winner.result.value;
        if (chunk.type === "text_delta") {
          assistantText += chunk.textDelta;
          yield { type: "emit", eventType: "llm_text_delta", payload: { delta: chunk.textDelta } };
        } else if (chunk.type === "reasoning_delta") {
          reasoningText += chunk.reasoningDelta;
          yield { type: "emit", eventType: "llm_reasoning_delta", payload: { delta: chunk.reasoningDelta } };
        } else if (chunk.type === "tool_call") {
          pendingToolCalls.push(chunk.toolCall);
        }
      }
    } catch (error) {
      // An aborted signal surfaces as a thrown error from the underlying HTTP call partway
      // through the stream — not a real failure, so it's treated exactly like the model
      // finishing early with whatever text had already streamed in. A non-abort error (a real
      // network failure, a malformed response, etc.) must still propagate: only swallow the
      // throw when it's actually a signal that fired, not merely correlated with one existing.
      if (!combinedSignal?.aborted) throw error;
    }
    yield {
      type: "emit",
      eventType: "llm_call_end",
      // Without this, 轨迹/trace inspection of an llm_call_end row showed nothing at all to
      // expand — the text this call actually produced (or, if it requested tools instead of
      // replying, how many) is exactly what someone reviewing the trace wants to see here.
      payload: { text: assistantText, toolCallCount: pendingToolCalls.length },
    };

    if (steeredMessage !== undefined) {
      conversation = [
        ...conversation,
        ...(assistantText ? [{ role: "assistant" as const, content: assistantText }] : []),
        { role: "user" as const, content: frameSteerMessage(steeredMessage) },
      ];
      continue;
    }

    // A cancelled turn is treated exactly like the model finishing early with no tool calls —
    // never proceeds to tool dispatch even if a tool_call chunk had already arrived, per the
    // "only cancellable during model streaming" scope decision.
    if (signal?.aborted) {
      return { messages: conversation, finalText: assistantText || "（已停止，无内容）", reasoningText };
    }

    if (pendingToolCalls.length === 0) {
      return { messages: conversation, finalText: assistantText, reasoningText };
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
