import { beforeEach, describe, expect, it } from "vitest";
import { stashPendingMessage, takePendingMessage } from "./pending-message";

// node 环境下没有 sessionStorage，用内存 Map 实现一个最小 Storage 替身。
function createMemoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, String(value));
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
    clear: () => map.clear(),
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    get length() {
      return map.size;
    },
  };
}

describe("pending-message", () => {
  beforeEach(() => {
    globalThis.sessionStorage = createMemoryStorage();
  });

  it("stash 后 take 返回内容，第二次 take 返回 null（读取即删除）", () => {
    stashPendingMessage("t1", "你好");
    expect(takePendingMessage("t1")).toBe("你好");
    expect(takePendingMessage("t1")).toBeNull();
  });

  it("不同 taskId 的 stash 互不影响", () => {
    stashPendingMessage("t1", "a");
    stashPendingMessage("t2", "b");
    expect(takePendingMessage("t1")).toBe("a");
    expect(takePendingMessage("t2")).toBe("b");
    expect(takePendingMessage("t1")).toBeNull();
  });

  it("未 stash 时 take 返回 null", () => {
    expect(takePendingMessage("nope")).toBeNull();
  });
});
