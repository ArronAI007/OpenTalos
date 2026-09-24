import { describe, expect, it } from "vitest";
import {
  appendStoppedNotice,
  dropStoppedNotice,
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

  it("done finalizes the assistant message", () => {
    let msgs = reduceChatEvent([], { type: "delta", text: "完" });
    msgs = reduceChatEvent(msgs, { type: "done", reply: "完" });
    expect(msgs[0]).toEqual({ id: "live-1", kind: "assistant", content: "完", streaming: false });
  });

  it("error becomes an error bubble", () => {
    const msgs = reduceChatEvent([], { type: "error", message: "boom" });
    expect(msgs[0]).toEqual({ id: "live-1", kind: "error", content: "boom" });
  });

  it("error finalizes streaming bubble and next reply starts fresh", () => {
    let msgs = reduceChatEvent([], { type: "delta", text: "正在查" });
    msgs = reduceChatEvent(msgs, { type: "error", message: "boom" });
    expect(msgs[0]).toEqual({ id: "live-1", kind: "assistant", content: "正在查", streaming: false });
    expect(msgs[1]).toEqual({ id: "live-2", kind: "error", content: "boom" });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "结果A" });
    expect(msgs[2]).toEqual({ id: "live-3", kind: "assistant", content: "结果A", streaming: true });
  });
});

describe("finalizeStreaming", () => {
  it("settles streaming assistant bubbles and keeps partial content", () => {
    let msgs = reduceChatEvent([], { type: "delta", text: "半截回复" });
    msgs = finalizeStreaming(msgs);
    expect(msgs[0]).toEqual({ id: "live-1", kind: "assistant", content: "半截回复", streaming: false });
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
    msgs = finalizeStreaming(msgs);
    expect(msgs[0]).toEqual({ id: "row-1", kind: "user", content: "问" });
    expect(msgs[1]).toMatchObject({ kind: "tool", name: "read_skill", result: undefined });
    expect(msgs[2]).toMatchObject({ kind: "assistant", streaming: false });
    msgs = reduceChatEvent(msgs, { type: "delta", text: "新回复" });
    expect(msgs[3]).toEqual({ id: "live-3", kind: "assistant", content: "新回复", streaming: true });
  });
});

describe("stopped notice", () => {
  it("appendStoppedNotice appends a stopped row after the finalized reply", () => {
    let msgs: UiMessage[] = [{ id: "row-1", kind: "user", content: "问" }];
    msgs = reduceChatEvent(msgs, { type: "delta", text: "半截" });
    msgs = finalizeStreaming(msgs);
    msgs = appendStoppedNotice(msgs);
    expect(msgs).toEqual([
      { id: "row-1", kind: "user", content: "问" },
      { id: "live-1", kind: "assistant", content: "半截", streaming: false },
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
});
