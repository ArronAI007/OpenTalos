import { describe, expect, it } from "vitest";
import { detectMentionQuery, stripMention } from "./agent-mention";

describe("detectMentionQuery", () => {
  it("行首的 @ 触发（空查询）", () => {
    expect(detectMentionQuery("@", 1)).toEqual({ start: 0, query: "" });
  });

  it("空白后的 @ 触发并带出过滤串", () => {
    expect(detectMentionQuery("帮我 @周报", 6)).toEqual({ start: 3, query: "周报" });
  });

  it("多行文本中当前行的 @ 也算", () => {
    expect(detectMentionQuery("第一行\n@abc", 9)).toEqual({ start: 4, query: "abc" });
  });

  it("非空白的字符后紧跟 @ 不触发（避开邮箱）", () => {
    expect(detectMentionQuery("foo@bar", 7)).toBeNull();
  });

  it("@ 与光标之间出现空白视为放弃", () => {
    expect(detectMentionQuery("@周报 助手", 6)).toBeNull();
  });

  it("光标之前的 @ 才算，光标之后的忽略", () => {
    expect(detectMentionQuery("abc@def", 3)).toBeNull();
  });

  it("没有 @ 返回 null", () => {
    expect(detectMentionQuery("普通文本", 4)).toBeNull();
  });

  it("越界光标按字符串长度截断", () => {
    expect(detectMentionQuery("@a", 99)).toEqual({ start: 0, query: "a" });
  });
});

describe("stripMention", () => {
  it("剔除 @query 并保留光标之后的文本", () => {
    const value = "帮我 @周报 整理";
    const mention = detectMentionQuery(value, 6);
    expect(mention).not.toBeNull();
    const result = stripMention(value, 6, mention!.start);
    expect(result.value).toBe("帮我  整理");
    expect(result.cursor).toBe(3);
  });

  it("空查询只删 @", () => {
    expect(stripMention("@", 1, 0)).toEqual({ value: "", cursor: 0 });
  });

  it("光标越界不越删", () => {
    expect(stripMention("@a", 99, 0)).toEqual({ value: "", cursor: 0 });
  });
});
