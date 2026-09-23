import { describe, expect, it } from "vitest";
import { isNearBottom, scrollToBottom, NEAR_BOTTOM_PX } from "./scroll-stick";

function el(scrollTop: number, scrollHeight: number, clientHeight = 500) {
  return { scrollTop, scrollHeight, clientHeight };
}

describe("isNearBottom", () => {
  it("贴底时为 true", () => {
    expect(isNearBottom(el(500, 1000))).toBe(true);
  });

  it("距底恰为阈值时为 true（边界取含）", () => {
    expect(isNearBottom(el(500 - NEAR_BOTTOM_PX, 1000))).toBe(true);
  });

  it("上翻超过阈值时为 false", () => {
    expect(isNearBottom(el(500 - NEAR_BOTTOM_PX - 1, 1000))).toBe(false);
    expect(isNearBottom(el(0, 1000))).toBe(false);
  });

  it("内容不足一屏（无需滚动）时为 true", () => {
    expect(isNearBottom(el(0, 300))).toBe(true);
  });
});

describe("scrollToBottom", () => {
  it("把 scrollTop 顶到 scrollHeight", () => {
    const target = el(0, 1000);
    scrollToBottom(target);
    expect(target.scrollTop).toBe(1000);
  });
});
