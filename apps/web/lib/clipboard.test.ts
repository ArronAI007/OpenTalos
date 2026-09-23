import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

// vitest 当前 environment: "node"，无真实 DOM：document / navigator 均用 vi.stubGlobal
// 注入最小 mock，afterEach 用 vi.unstubAllGlobals() 完整还原，保证用例间无泄漏。
function stubClipboard(writeText?: (text: string) => Promise<void>) {
  vi.stubGlobal("navigator", { clipboard: writeText ? { writeText } : undefined });
}

interface FallbackSpies {
  textarea: { value: string; style: Record<string, string>; select: ReturnType<typeof vi.fn> };
  appendChild: ReturnType<typeof vi.fn>;
  removeChild: ReturnType<typeof vi.fn>;
  execCommand: ReturnType<typeof vi.fn>;
}

function stubDocument(execResult: boolean | (() => boolean)): FallbackSpies {
  const spies: FallbackSpies = {
    textarea: { value: "", style: {}, select: vi.fn() },
    appendChild: vi.fn(),
    removeChild: vi.fn(),
    execCommand: typeof execResult === "function" ? vi.fn(execResult) : vi.fn(() => execResult),
  };
  vi.stubGlobal("document", {
    createElement: vi.fn(() => spies.textarea),
    body: { appendChild: spies.appendChild, removeChild: spies.removeChild },
    execCommand: spies.execCommand,
  });
  return spies;
}

describe("copyText", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("navigator.clipboard.writeText 成功时返回 true，且不触碰 DOM fallback", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    await expect(copyText("hello")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(writeText).toHaveBeenCalledTimes(1);
  });

  it("writeText 抛错时回退 execCommand，成功返回 true 并完成挂载-复制-移除全流程", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    const spies = stubDocument(true);
    await expect(copyText("http://localhost:3000/t/abc")).resolves.toBe(true);
    expect(spies.textarea.value).toBe("http://localhost:3000/t/abc");
    expect(spies.appendChild).toHaveBeenCalledWith(spies.textarea);
    expect(spies.textarea.select).toHaveBeenCalled();
    expect(spies.execCommand).toHaveBeenCalledWith("copy");
    expect(spies.removeChild).toHaveBeenCalledWith(spies.textarea);
  });

  it("navigator.clipboard 不存在（非安全上下文）时走 fallback", async () => {
    stubClipboard(undefined);
    const spies = stubDocument(true);
    await expect(copyText("x")).resolves.toBe(true);
    expect(spies.execCommand).toHaveBeenCalledWith("copy");
  });

  it("writeText 失败且 execCommand 返回 false 时返回 false", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    stubDocument(false);
    await expect(copyText("x")).resolves.toBe(false);
  });

  it("两条路径都不可用（无 clipboard 且无 document）时返回 false，不抛异常", async () => {
    stubClipboard(undefined);
    await expect(copyText("x")).resolves.toBe(false);
  });

  it("execCommand 抛错时返回 false，且临时元素仍被移除", async () => {
    stubClipboard(undefined);
    const spies = stubDocument(() => {
      throw new Error("execCommand unsupported");
    });
    await expect(copyText("x")).resolves.toBe(false);
    expect(spies.removeChild).toHaveBeenCalledWith(spies.textarea);
  });
});
