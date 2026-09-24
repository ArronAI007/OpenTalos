import { describe, expect, it } from "vitest";
import {
  appendStoppedNotice,
  dropStoppedNotice,
  dropSuggestions,
  dropTurn,
  finalizeStreaming,
  parseSseBlock,
  reduceChatEvent,
  shouldShowThinkingHint,
  type UiMessage,
} from "./chat-events";

describe("parseSseBlock", () => {
  it("parses a data frame", () => {
    expect(parseSseBlock('data: {"type":"delta","text":"你"}')).toEqual({ type: "delta", text: "你" });
  });
  it("returns null for empty or non-data block", () => {
    expect(parseSseBlock("")).toBeNull();
    expect(parseSseBlock(": keep-alive")).toBeNull();
  });
});

describe("reduceChatEvent", () => {
  it("appends delta text to the streaming assistant message", () => {
    let msgs: UiMessage[] = [];
    msgs = reduceChatEvent(msgs, { type: "delta", text: "你" });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "好" });
    expect(msgs).toEqual([{ id: "live-1", kind: "assistant", content: "你好", streaming: true }]);
  });

  it("pairs tool_result with the earliest unmatched tool_call of the same name", () => {
    let msgs: UiMessage[] = [];
    msgs = reduceChatEvent(msgs, { type: "tool_call", name: "read_skill", arguments: { skill_name: "date" } });
    msgs = reduceChatEvent(msgs, { type: "tool_call", name: "run_skill_script", arguments: { skill_name: "date" } });
    msgs = reduceChatEvent(msgs, { type: "tool_result", name: "read_skill", result: "# date …", ok: true });
    expect(msgs[0]).toMatchObject({ id: "live-1", kind: "tool", name: "read_skill", ok: true, result: "# date …" });
    expect(msgs[1]).toMatchObject({ id: "live-2", kind: "tool", name: "run_skill_script", result: undefined });
  });

  it("done finalizes the assistant message and stamps completedAt from the injected now", () => {
    let msgs = reduceChatEvent([], { type: "delta", text: "完" });
    msgs = reduceChatEvent(msgs, { type: "done", reply: "完" }, 1700000000000);
    expect(msgs[0]).toEqual({
      id: "live-1",
      kind: "assistant",
      content: "完",
      streaming: false,
      completedAt: 1700000000000,
    });
  });

  it("error becomes an error bubble", () => {
    const msgs = reduceChatEvent([], { type: "error", message: "boom" });
    expect(msgs[0]).toEqual({ id: "live-1", kind: "error", content: "boom" });
  });

  it("error finalizes streaming bubble (stamped) and next reply starts fresh", () => {
    let msgs = reduceChatEvent([], { type: "delta", text: "正在查" });
    msgs = reduceChatEvent(msgs, { type: "error", message: "boom" }, 1700000000001);
    expect(msgs[0]).toEqual({
      id: "live-1",
      kind: "assistant",
      content: "正在查",
      streaming: false,
      completedAt: 1700000000001,
    });
    expect(msgs[1]).toEqual({ id: "live-2", kind: "error", content: "boom" });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "结果A" });
    expect(msgs[2]).toEqual({ id: "live-3", kind: "assistant", content: "结果A", streaming: true });
  });
});

describe("finalizeStreaming", () => {
  it("settles streaming assistant bubbles, keeps partial content and stamps completedAt", () => {
    let msgs = reduceChatEvent([], { type: "delta", text: "半截回复" });
    msgs = finalizeStreaming(msgs, 1700000000002);
    expect(msgs[0]).toEqual({
      id: "live-1",
      kind: "assistant",
      content: "半截回复",
      streaming: false,
      completedAt: 1700000000002,
    });
  });

  it("returns the same reference when nothing is streaming (no-op fast path)", () => {
    const msgs: UiMessage[] = [
      { id: "row-1", kind: "user", content: "问" },
      { id: "row-2", kind: "assistant", content: "答" },
    ];
    expect(finalizeStreaming(msgs)).toBe(msgs);
  });

  it("leaves user and tool bubbles untouched, and the next reply starts fresh", () => {
    let msgs: UiMessage[] = [{ id: "row-1", kind: "user", content: "问" }];
    msgs = reduceChatEvent(msgs, { type: "tool_call", name: "read_skill", arguments: {} });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "查" });
    msgs = finalizeStreaming(msgs, 1700000000003);
    expect(msgs[0]).toEqual({ id: "row-1", kind: "user", content: "问" });
    expect(msgs[1]).toMatchObject({ kind: "tool", name: "read_skill", result: undefined });
    expect(msgs[2]).toMatchObject({ kind: "assistant", streaming: false, completedAt: 1700000000003 });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "新回复" });
    expect(msgs[3]).toEqual({ id: "live-3", kind: "assistant", content: "新回复", streaming: true });
  });
});

describe("stopped notice", () => {
  it("appendStoppedNotice appends a stopped row after the finalized reply", () => {
    let msgs: UiMessage[] = [{ id: "row-1", kind: "user", content: "问" }];
    msgs = reduceChatEvent(msgs, { type: "delta", text: "半截" });
    msgs = finalizeStreaming(msgs, 1700000000004);
    msgs = appendStoppedNotice(msgs);
    expect(msgs).toEqual([
      { id: "row-1", kind: "user", content: "问" },
      { id: "live-1", kind: "assistant", content: "半截", streaming: false, completedAt: 1700000000004 },
      { id: "live-2", kind: "stopped" },
    ]);
  });

  it("appendStoppedNotice is idempotent (returns the same reference if one already exists)", () => {
    const once = appendStoppedNotice([]);
    expect(appendStoppedNotice(once)).toBe(once);
  });

  it("appendStoppedNotice still appends when only historical row-N stopped rows exist", () => {
    // 回归：旧守卫查"任意 stopped"，历史停止行（服务端落库的轮次痕迹）会把它短路，
    // 导致会话里停止过一次之后，再次停止时提示永远加不上
    const prev: UiMessage[] = [
      { id: "row-9", kind: "user", content: "旧问" },
      { id: "row-10", kind: "assistant", content: "旧答" },
      { id: "row-11", kind: "stopped" },
      { id: "row-12", kind: "user", content: "新问" },
      { id: "live-1", kind: "assistant", content: "半截", streaming: false },
    ];
    const next = appendStoppedNotice(prev);
    expect(next[next.length - 1]).toEqual({ id: "live-2", kind: "stopped" });
  });

  it("dropStoppedNotice removes the notice and keeps other rows; no-op fast path without one", () => {
    let msgs: UiMessage[] = [{ id: "row-1", kind: "user", content: "问" }];
    msgs = reduceChatEvent(msgs, { type: "delta", text: "半截" });
    msgs = finalizeStreaming(msgs);
    const withNotice = appendStoppedNotice(msgs);
    expect(dropStoppedNotice(withNotice)).toEqual(msgs);
    expect(dropStoppedNotice(msgs)).toBe(msgs);
  });

  it("dropStoppedNotice keeps historical (row-N) stopped rows — they are persisted turn traces", () => {
    let msgs: UiMessage[] = [
      { id: "row-9", kind: "user", content: "旧问" },
      { id: "row-10", kind: "assistant", content: "旧答" },
      { id: "row-11", kind: "stopped" },
    ];
    // 会话内又发生一次停止，再发送时只应清掉 live 提示，历史痕迹保留
    msgs = appendStoppedNotice(msgs);
    const dropped = dropStoppedNotice(msgs);
    expect(dropped.map((m) => m.id)).toEqual(["row-9", "row-10", "row-11"]);
  });
});

describe("user_stored event", () => {
  it("rewrites the latest live user bubble to its stored row id and stamps the server time", () => {
    const msgs: UiMessage[] = [
      { id: "row-1", kind: "user", content: "旧问", completedAt: 1700000000000 },
      { id: "live-1", kind: "user", content: "新问", completedAt: 1700000000001 },
    ];
    const next = reduceChatEvent(msgs, { type: "user_stored", id: 42, created_at: "2026-09-24T11:23:00.000000" });
    expect(next[0]).toBe(msgs[0]); // 历史行不动
    expect(next[1]).toEqual({
      id: "row-42",
      kind: "user",
      content: "新问",
      completedAt: new Date(2026, 8, 24, 11, 23).getTime(), // 无时区后缀按本地解析
    });
  });

  it("no-ops with the same reference when no live user bubble exists (e.g. late event after refresh)", () => {
    const msgs: UiMessage[] = [{ id: "row-1", kind: "user", content: "问" }];
    expect(reduceChatEvent(msgs, { type: "user_stored", id: 2, created_at: "2026-09-24T11:23:00.000000" })).toBe(msgs);
  });
});

describe("dropTurn", () => {
  it("drops the user bubble plus everything up to (not incl.) the next user bubble", () => {
    const msgs: UiMessage[] = [
      { id: "row-1", kind: "user", content: "一" },
      { id: "row-2", kind: "assistant", content: "答一" },
      { id: "row-3", kind: "user", content: "二" },
      { id: "live-1", kind: "tool", name: "echo", arguments: {}, ok: true, result: "..." },
      { id: "row-4", kind: "assistant", content: "答二" },
      { id: "live-2", kind: "stopped" },
    ];
    expect(dropTurn(msgs, "row-3").map((m) => m.id)).toEqual(["row-1", "row-2"]);
  });

  it("mid-conversation turn dies while earlier and later turns survive", () => {
    const msgs: UiMessage[] = [
      { id: "row-1", kind: "user", content: "一" },
      { id: "row-2", kind: "assistant", content: "答一" },
      { id: "row-3", kind: "user", content: "二" },
      { id: "row-4", kind: "assistant", content: "答二" },
      { id: "row-5", kind: "user", content: "三" },
      { id: "row-6", kind: "assistant", content: "答三" },
    ];
    expect(dropTurn(msgs, "row-3").map((m) => m.id)).toEqual(["row-1", "row-2", "row-5", "row-6"]);
  });

  it("no-ops with the same reference on unknown id or non-user target", () => {
    const msgs: UiMessage[] = [
      { id: "row-1", kind: "user", content: "一" },
      { id: "row-2", kind: "assistant", content: "答一" },
    ];
    expect(dropTurn(msgs, "row-99")).toBe(msgs);
    expect(dropTurn(msgs, "row-2")).toBe(msgs); // 目标是 assistant：不发生删除
  });
});

describe("reasoning（思维链）", () => {
  it("reasoning events accumulate into one streaming bubble", () => {
    let msgs: UiMessage[] = [];
    msgs = reduceChatEvent(msgs, { type: "reasoning", text: "先想" });
    msgs = reduceChatEvent(msgs, { type: "reasoning", text: "再想" });
    expect(msgs).toEqual([{ id: "live-1", kind: "reasoning", content: "先想再想", streaming: true }]);
  });

  it("first content delta settles the reasoning bubble and starts a fresh assistant bubble", () => {
    let msgs = reduceChatEvent([], { type: "reasoning", text: "想了想" });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "答" });
    expect(msgs).toEqual([
      { id: "live-1", kind: "reasoning", content: "想了想", streaming: false },
      { id: "live-2", kind: "assistant", content: "答", streaming: true },
    ]);
  });

  it("done settles the reasoning bubble too (reply without any streamed content)", () => {
    const msgs = reduceChatEvent([], { type: "reasoning", text: "想了想" });
    const next = reduceChatEvent(msgs, { type: "done", reply: "整段" }, 1700000000005);
    expect(next[0]).toEqual({ id: "live-1", kind: "reasoning", content: "想了想", streaming: false });
    expect(next[1]).toMatchObject({ kind: "assistant", content: "整段", streaming: false });
  });

  it("settling is idempotent by reference: a second delta leaves the reasoning row untouched", () => {
    let msgs = reduceChatEvent([], { type: "reasoning", text: "想" });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "一" });
    const reasoningRow = msgs[0];
    msgs = reduceChatEvent(msgs, { type: "delta", text: "二" });
    expect(msgs[0]).toBe(reasoningRow);
  });

  it("finalizeStreaming settles the reasoning bubble as well (user stops mid-thought)", () => {
    let msgs = reduceChatEvent([], { type: "reasoning", text: "想到一半" });
    msgs = finalizeStreaming(msgs, 1700000000006);
    expect(msgs[0]).toEqual({ id: "live-1", kind: "reasoning", content: "想到一半", streaming: false });
  });

  it("dropTurn removes the reasoning row with the rest of the turn", () => {
    const msgs: UiMessage[] = [
      { id: "row-1", kind: "user", content: "问" },
      { id: "live-1", kind: "reasoning", content: "想", streaming: false },
      { id: "row-2", kind: "assistant", content: "答" },
    ];
    expect(dropTurn(msgs, "row-1")).toEqual([]);
  });
});

describe("shouldShowThinkingHint", () => {
  it("shows while busy with nothing streaming yet", () => {
    const msgs: UiMessage[] = [{ id: "live-1", kind: "user", content: "问" }];
    expect(shouldShowThinkingHint(msgs, true)).toBe(true);
  });

  it("hides once reasoning or content starts streaming, and when not busy", () => {
    const reasoning: UiMessage[] = [{ id: "live-1", kind: "reasoning", content: "想", streaming: true }];
    expect(shouldShowThinkingHint(reasoning, true)).toBe(false);
    const delta: UiMessage[] = [{ id: "live-1", kind: "assistant", content: "答", streaming: true }];
    expect(shouldShowThinkingHint(delta, true)).toBe(false);
    expect(shouldShowThinkingHint([], false)).toBe(false);
  });

  it("settled bubbles from a previous turn do not suppress the hint", () => {
    const msgs: UiMessage[] = [
      { id: "row-1", kind: "reasoning", content: "旧想", streaming: false },
      { id: "row-2", kind: "assistant", content: "旧答", streaming: false },
      { id: "live-1", kind: "user", content: "新问" },
    ];
    expect(shouldShowThinkingHint(msgs, true)).toBe(true);
  });

  it("hides after done while the stream stays open computing suggestions", () => {
    // 回归：done 后 SSE 未关（服务端在同流上算 suggestions，busy 仍为 true），
    // 占位若再现会带着品牌头读作「第二轮思考」
    const msgs: UiMessage[] = [
      { id: "live-1", kind: "user", content: "问" },
      { id: "live-2", kind: "assistant", content: "答", streaming: false, completedAt: 1 },
    ];
    expect(shouldShowThinkingHint(msgs, true)).toBe(false);
  });
});

describe("suggestions", () => {
  it("appends a suggestions row after done-finalized assistant", () => {
    const prev: UiMessage[] = [
      { id: "row-1", kind: "user", content: "问" },
      { id: "live-1", kind: "assistant", content: "答", streaming: false, completedAt: 1 },
    ];
    const next = reduceChatEvent(prev, { type: "suggestions", items: ["然后呢？"] });
    expect(next.map((m) => m.kind)).toEqual(["user", "assistant", "suggestions"]);
    const row = next[next.length - 1];
    if (row.kind !== "suggestions") throw new Error("unreachable");
    expect(row.items).toEqual(["然后呢？"]);
  });

  it("replaces an existing suggestions row instead of stacking", () => {
    const prev: UiMessage[] = [
      { id: "live-1", kind: "suggestions", items: ["旧建议"] },
      { id: "live-2", kind: "assistant", content: "答", streaming: false, completedAt: 1 },
    ];
    const next = reduceChatEvent(prev, { type: "suggestions", items: ["新建议"] });
    expect(next.filter((m) => m.kind === "suggestions")).toHaveLength(1);
    const row = next.find((m) => m.kind === "suggestions");
    if (row?.kind !== "suggestions") throw new Error("unreachable");
    expect(row.items).toEqual(["新建议"]);
  });

  it("dropSuggestions removes suggestion rows, keeps everything else", () => {
    const prev: UiMessage[] = [
      { id: "row-1", kind: "user", content: "问" },
      { id: "row-2", kind: "assistant", content: "答" },
      { id: "live-3", kind: "suggestions", items: ["然后呢？"] },
    ];
    expect(dropSuggestions(prev).map((m) => m.id)).toEqual(["row-1", "row-2"]);
  });

  it("dropSuggestions no-ops with the same reference when no suggestions", () => {
    const prev: UiMessage[] = [{ id: "row-1", kind: "assistant", content: "答" }];
    expect(dropSuggestions(prev)).toBe(prev);
  });
});
