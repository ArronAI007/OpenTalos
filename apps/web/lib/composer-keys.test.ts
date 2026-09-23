import { describe, expect, it } from "vitest";
import { shouldSubmitOnEnter } from "./composer-keys";

describe("shouldSubmitOnEnter", () => {
  it("Enter 发送", () => {
    expect(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false })).toBe(true);
  });

  it("Shift+Enter 换行，不发送", () => {
    expect(shouldSubmitOnEnter({ key: "Enter", shiftKey: true, isComposing: false })).toBe(false);
  });

  it("IME 候选态 Enter 不发送", () => {
    expect(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: true })).toBe(false);
  });

  it("其他键不发送", () => {
    expect(shouldSubmitOnEnter({ key: "a", shiftKey: false, isComposing: false })).toBe(false);
    expect(shouldSubmitOnEnter({ key: "Escape", shiftKey: false, isComposing: false })).toBe(false);
  });
});
