import { describe, expect, it } from "vitest";
import { parseSseBlock, reduceChatEvent, type UiMessage } from "./chat-events";

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
