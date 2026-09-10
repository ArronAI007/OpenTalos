import { defineConfig } from "@playwright/test";

const DATABASE_URL = "postgres://postgres:postgres@localhost:5433/postgres";
const ADMIN_API_KEY = "e2e-admin-key";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:5173",
  },
  webServer: [
    {
      command: "pnpm --filter @opentalos/worker start",
      env: { DATABASE_URL, HEALTH_PORT: "3002", MODEL_PROVIDER: "mock" },
      url: "http://localhost:3002",
      reuseExistingServer: !process.env.CI,
      timeout: 20_000,
    },
    {
      // NOTE (deviation from the plan text): the plan's original readiness check was a GET to
      // `/runs/healthcheck?sessionId=healthcheck`, on the assumption that Playwright's webServer
      // readiness probe only cares about connectivity, not HTTP status. That's not true for the
      // installed @playwright/test (1.63.0): a `url`-based check requires status 200-403 (see
      // playwright-core's isURLAvailable) and explicitly rejects 404. Worse, Playwright starts
      // every webServer (and waits for each to become ready) BEFORE running globalSetup, so at
      // readiness-check time the `checkpoints` table this route queries doesn't exist yet, and
      // Fastify's uncaught-error handler turns that into a 500 (not the expected 404) - which
      // would fail readiness even under the old assumption. Using `port` instead of `url` makes
      // Playwright do a plain TCP connect check instead (see isPortUsed in
      // playwright-core/lib/coreBundle.js) - Fastify's `app.listen()` binds the port immediately,
      // independent of whether any request has touched Postgres yet, so this is a truer match for
      // "is the process up" than the DB-dependent route this plan originally pointed at.
      command: "pnpm --filter @opentalos/api start",
      env: { DATABASE_URL, PORT: "3001", ADMIN_API_KEY, MODEL_PROVIDER: "mock" },
      port: 3001,
      reuseExistingServer: !process.env.CI,
      timeout: 20_000,
    },
    {
      command: "pnpm --filter @opentalos/web dev",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 20_000,
    },
    {
      command: "pnpm --filter @opentalos/admin dev",
      url: "http://localhost:5174",
      reuseExistingServer: !process.env.CI,
      timeout: 20_000,
    },
  ],
});
