import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  // 默认 node（纯函数测试快）；组件测试文件用 `// @vitest-environment jsdom` 单独切到 jsdom。
  test: { environment: "node", setupFiles: ["./vitest.setup.ts"] },
  resolve: { alias: { "@": path.resolve(__dirname) } },
});
