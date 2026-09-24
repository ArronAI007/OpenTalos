import { describe, expect, it } from "vitest";
import {
  appendStoppedNotice,
  dropStoppedNotice,
  dropTurn,
  finalizeStreaming,
  parseSseBlock,
  reduceChatEvent,
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
