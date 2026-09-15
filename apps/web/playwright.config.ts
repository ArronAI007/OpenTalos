import { defineConfig } from "@playwright/test";

// Port 5434 — the E2E-only Postgres (apps/web/e2e/docker-compose.yml), never the regular local-dev
// Postgres on 5433 (scripts/docker-compose.postgres.yml, what .env's DATABASE_URL points at).
// global-setup.ts DROPs and reseeds every table on this database on every run; pointing this at
// the dev database would destroy real tenant/API-key/chat data every time the suite runs.
//
// Caveat this doesn't fully solve: `reuseExistingServer: !process.env.CI` below means that if a
// real dev stack (scripts/dev.sh start) is ALREADY running on ports 3001/3002/5173/5174, these
// webServer entries reuse those real processes (still pointed at the real 5433 database) instead
// of starting fresh ones against this isolated 5434 database — the DROP/reseed here then has no
// effect on what the tests actually exercise. Stop the real dev stack first
// (`scripts/dev.sh stop worker api web admin`) for a truly clean, isolated E2E run.
const DATABASE_URL = "postgres://postgres:postgres@localhost:5434/postgres";
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
