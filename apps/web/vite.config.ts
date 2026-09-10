import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/runs": "http://localhost:3001",
    },
  },
  test: {
    environment: "node",
    // Playwright's E2E specs live under e2e/ and use @playwright/test's own `test()` — Vitest's
    // default file glob would otherwise pick up `e2e/*.spec.ts` too and fail to run it.
    exclude: ["e2e/**", "node_modules/**"],
  },
});
