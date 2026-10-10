import { afterEach } from "vitest";

// 只在 jsdom 环境（组件测试）里启用 jest-dom 匹配器与 RTL 清理；纯函数测试跑在 node 下，
// 此时 document 未定义，跳过即可（避免在 node 环境 import 依赖 DOM 的包）。
if (typeof document !== "undefined") {
  await import("@testing-library/jest-dom/vitest");
  const { cleanup } = await import("@testing-library/react");
  afterEach(() => {
    cleanup();
  });
}
