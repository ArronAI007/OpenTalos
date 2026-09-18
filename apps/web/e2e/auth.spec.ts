import { test, expect } from "@playwright/test";

const ADMIN_API_KEY = "e2e-admin-key";
const API_BASE = "http://localhost:3001";
const ADMIN_BASE = "http://localhost:3001/admin";

// Date.now() alone can collide (parallel workers, retries, or two tests firing within the same
// millisecond); a random suffix makes username collisions practically impossible without needing
// a shared counter across test files. Kept short (no Date.now() prefix) since usernames are
// capped at 32 chars server-side (see apps/api/src/routes/auth.ts's MAX_USERNAME_LENGTH) and the
// longest prefix used here ("web-register") plus a full timestamp would exceed that.
function uniqueUsername(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

async function createTenantAndKey(name: string, maxConcurrency?: number) {
  const createRes = await fetch(`${ADMIN_BASE}/tenants`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${ADMIN_API_KEY}` },
    body: JSON.stringify({ name, maxConcurrency }),
  });
  const tenant = await createRes.json();
  const keyRes = await fetch(`${ADMIN_BASE}/tenants/${tenant.id}/api-keys`, {
    method: "POST",
    headers: { Authorization: `Bearer ${ADMIN_API_KEY}` },
  });
  const { rawKey } = await keyRes.json();
  return { tenant, rawKey };
}

test("two tenants with different quotas get differentiated concurrency in the same poll cycle", async () => {
  const { rawKey: rawKeyLow } = await createTenantAndKey("quota-e2e-low", 1);
  const { rawKey: rawKeyHigh } = await createTenantAndKey("quota-e2e-high", 5);

  interface StartedRun {
    runId: string;
    sessionId: string;
  }

  async function startRuns(rawKey: string, sessionPrefix: string, count: number): Promise<StartedRun[]> {
    const runs: StartedRun[] = [];
    for (let i = 0; i < count; i++) {
      const sessionId = `${sessionPrefix}-${i}`;
      const res = await fetch(`${API_BASE}/runs?sessionId=${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${rawKey}` },
        body: JSON.stringify({ message: `quota test ${i}` }),
      });
      const { runId } = await res.json();
      runs.push({ runId, sessionId });
    }
    return runs;
  }

  // NOTE (deviation from the plan text): the plan started 3 runs per tenant and waited
  // 1000ms (bumpable to 2000-3000ms) expecting the quota=1 tenant to have claimed at most 1 run
  // by then. Empirically, a single chat-agent run reaches "paused" in ~100-140ms end to
  // end — the same order of magnitude as the worker's 100ms poll interval — so with only 3 runs
  // *any* wait long enough to reliably observe a status change (needed to avoid false negatives
  // from polling too early) is also long enough for a quota=1 tenant to have serially finished
  // all 3 (verified directly: at 1000ms and 3000ms waits, lowClaimed was 3/3, i.e. no
  // differentiation was observable at all — not a flaky pass/fail, a deterministic non-result).
  // Increasing the wait further only makes this worse, not better, since it gives the quota=1
  // tenant more time to catch up. The fix that actually produces a stable, differentiated signal
  // is a wider batch (6 runs per tenant) sampled at a wait (300ms) comfortably past one
  // low-quota task's latency but short enough that quota=1's strict serialization can't clear
  // the whole batch, while quota=5's parallelism can (verified over 15 repeated trials at
  // count=6/wait=300ms: highClaimed was 6/6 every time, lowClaimed ranged 3-4/6 every time —
  // zero failures, comfortable margin).
  const RUN_COUNT = 6;
  const lowRuns = await startRuns(rawKeyLow, "quota-low", RUN_COUNT);
  const highRuns = await startRuns(rawKeyHigh, "quota-high", RUN_COUNT);

  await new Promise((resolve) => setTimeout(resolve, 300));

  async function countClaimed(rawKey: string, runs: StartedRun[]): Promise<number> {
    let claimed = 0;
    for (const { runId, sessionId } of runs) {
      // NOTE (deviation from the plan text): the plan originally polled with a fixed, unrelated
      // `sessionId=irrelevant-for-this-check` query param. apps/api's GET /runs/:runId route
      // (see apps/api/src/routes/runs.ts) deliberately 403s any request whose sessionId doesn't
      // match the run's own checkpoint.sessionId — a real security property from Task 3, not a
      // bug — so that fixed placeholder made every single poll here fail with 403 regardless of
      // timing, which is why this test failed identically (0 claimed on both sides) at both 1s
      // and 3s waits. Polling with the same sessionId each run was actually started under fixes
      // this without weakening the assertion.
      const res = await fetch(`${API_BASE}/runs/${runId}?sessionId=${sessionId}`, {
        headers: { Authorization: `Bearer ${rawKey}` },
      });
      // A run that was claimed and started executing has left "running"'s initial insert state
      // in some observable way; simplest reliable signal here is status !== "running" OR the
      // run's checkpoint having moved past the entry node — for the chat-agent graph, the
      // fastest observable divergence within ~1s is whether the run is still exactly at its
      // initial state. Since every run uses the same trivial-ish graph and we only need a COUNT
      // comparison (not exact status), treat any run whose GET succeeds with status "paused" or
      // "done" (i.e., progressed at least to the first HITL pause) as "claimed this cycle".
      if (res.ok) {
        const body = await res.json();
        if (body.status === "paused" || body.status === "done") claimed += 1;
      }
    }
    return claimed;
  }

  const lowClaimed = await countClaimed(rawKeyLow, lowRuns);
  const highClaimed = await countClaimed(rawKeyHigh, highRuns);

  // The quota=1 tenant must not have been able to serially clear the whole batch in this window
  // (proving it was actually throttled), while the quota=5 tenant — running the same graph
  // against the same worker at the same time — must have gotten further, proving the two
  // tenants' concurrency really is resolved independently rather than sharing one global cap.
  expect(lowClaimed).toBeLessThan(RUN_COUNT);
  expect(highClaimed).toBeGreaterThan(lowClaimed);
});

test("registering a new account via the web UI logs straight into a working chat session", async ({ page }) => {
  await page.goto("/");
  const registerDialog = page.getByRole("dialog", { name: "注册账号" });
  await page.getByRole("button", { name: "注册" }).click();
  await registerDialog.getByPlaceholder("用户名").fill(uniqueUsername("web-register"));
  await registerDialog.getByPlaceholder("密码（至少 8 位）").fill("password123");
  await registerDialog.getByPlaceholder("确认密码").fill("password123");
  await registerDialog.getByRole("button", { name: "注册" }).click();

  await page.getByPlaceholder("给智能体发消息").fill("你好");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("你好").first()).toBeVisible();
});

test("a revoked API key is rejected by the chat UI, which asks the user to re-enter one", async ({ page }) => {
  const username = uniqueUsername("revoke-web");
  await page.goto("/");
  const registerDialog = page.getByRole("dialog", { name: "注册账号" });
  await page.getByRole("button", { name: "注册" }).click();
  await registerDialog.getByPlaceholder("用户名").fill(username);
  await registerDialog.getByPlaceholder("密码（至少 8 位）").fill("password123");
  await registerDialog.getByPlaceholder("确认密码").fill("password123");
  await registerDialog.getByRole("button", { name: "注册" }).click();

  // Confirms the session's API key genuinely works before it gets revoked.
  await expect(page.getByPlaceholder("给智能体发消息")).toBeVisible();

  const usersRes = await fetch(`${ADMIN_BASE}/users`, { headers: { Authorization: `Bearer ${ADMIN_API_KEY}` } });
  const user = (await usersRes.json()).find((u: { username: string; tenantId: string }) => u.username === username);
  const keysRes = await fetch(`${ADMIN_BASE}/tenants/${user.tenantId}/api-keys`, {
    headers: { Authorization: `Bearer ${ADMIN_API_KEY}` },
  });
  const keys = await keysRes.json();
  await fetch(`${ADMIN_BASE}/api-keys/${keys[0].id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${ADMIN_API_KEY}` },
  });

  // The revoked key is still in localStorage; sending now hits the server and gets a 401.
  await page.getByPlaceholder("给智能体发消息").fill("hello");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("密钥无效或已被吊销，请重新输入")).toBeVisible({ timeout: 5000 });
  // App.tsx unmounts the session and remounts a fresh ApiKeyGate once hasApiKey flips back to
  // false, so the gate's login form (not the register dialog) is what re-appears for re-entry.
  await expect(page.getByPlaceholder("用户名")).toBeVisible();
  await expect(page.getByPlaceholder("密码")).toBeVisible();
});

test("registering then logging out and back in with the same credentials works", async ({ page }) => {
  const username = uniqueUsername("web-login");
  await page.goto("/");
  const registerDialog = page.getByRole("dialog", { name: "注册账号" });
  await page.getByRole("button", { name: "注册" }).click();
  await registerDialog.getByPlaceholder("用户名").fill(username);
  await registerDialog.getByPlaceholder("密码（至少 8 位）").fill("password123");
  await registerDialog.getByPlaceholder("确认密码").fill("password123");
  await registerDialog.getByRole("button", { name: "注册" }).click();
  await expect(page.getByPlaceholder("给智能体发消息")).toBeVisible();

  // Simulate "logging out" by clearing the stored key and reloading into the gate.
  await page.evaluate(() => localStorage.removeItem("opentalos-api-key"));
  await page.reload();

  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码").fill("password123");
  await page.getByRole("button", { name: "登录" }).click();

  await page.getByPlaceholder("给智能体发消息").fill("hello again");
  await page.getByRole("button", { name: "发送" }).click();
  // NOTE (deviation from the plan text): the message text also appears in the auto-generated
  // session title (sidebar entry + <h1>), so an unscoped getByText matches 3 elements and fails
  // Playwright's strict mode. .first() is what the sibling "你好" assertion above already uses
  // for the identical reason — applying it here too, consistently.
  await expect(page.getByText("hello again").first()).toBeVisible();
});

test("registration rejects a mismatched confirm-password without hitting the server", async ({ page }) => {
  await page.goto("/");
  const registerDialog = page.getByRole("dialog", { name: "注册账号" });
  await page.getByRole("button", { name: "注册" }).click();
  await registerDialog.getByPlaceholder("用户名").fill(uniqueUsername("mismatch"));
  await registerDialog.getByPlaceholder("密码（至少 8 位）").fill("password123");
  await registerDialog.getByPlaceholder("确认密码").fill("different-password");
  await registerDialog.getByRole("button", { name: "注册" }).click();

  await expect(registerDialog.getByText("两次输入的密码不一致")).toBeVisible();
  // Still on the gate, not logged in.
  await expect(page.getByPlaceholder("给智能体发消息")).not.toBeVisible();
});

test("logging in with a wrong password shows an error and stays on the gate", async ({ page }) => {
  const username = uniqueUsername("wrongpw");
  await page.goto("/");
  const registerDialog = page.getByRole("dialog", { name: "注册账号" });
  await page.getByRole("button", { name: "注册" }).click();
  await registerDialog.getByPlaceholder("用户名").fill(username);
  await registerDialog.getByPlaceholder("密码（至少 8 位）").fill("password123");
  await registerDialog.getByPlaceholder("确认密码").fill("password123");
  await registerDialog.getByRole("button", { name: "注册" }).click();
  await expect(page.getByPlaceholder("给智能体发消息")).toBeVisible();

  await page.evaluate(() => localStorage.removeItem("opentalos-api-key"));
  await page.reload();
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码").fill("totally-wrong-password");
  await page.getByRole("button", { name: "登录" }).click();

  await expect(page.getByText("用户名或密码错误")).toBeVisible();
  await expect(page.getByPlaceholder("给智能体发消息")).not.toBeVisible();
});

test("a banned user cannot log in and sees a clear reason", async ({ page }) => {
  const username = uniqueUsername("banned-web");
  const registerRes = await fetch("http://localhost:3001/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password: "password123" }),
  });
  expect(registerRes.status).toBe(201);

  const usersRes = await fetch(`${ADMIN_BASE}/users`, { headers: { Authorization: `Bearer ${ADMIN_API_KEY}` } });
  const user = (await usersRes.json()).find((u: { username: string }) => u.username === username);
  await fetch(`${ADMIN_BASE}/users/${user.id}/ban`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${ADMIN_API_KEY}` },
  });

  await page.goto("/");
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码").fill("password123");
  await page.getByRole("button", { name: "登录" }).click();

  await expect(page.getByText("账号已被封禁")).toBeVisible();
});

test("admin can see a registered user in the Users tab, ban them, unban them, then soft-delete them", async ({
  page,
  context,
}) => {
  const username = uniqueUsername("admin-manage");
  const registerRes = await fetch("http://localhost:3001/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password: "password123" }),
  });
  expect(registerRes.status).toBe(201);

  const adminPage = await context.newPage();
  await adminPage.goto("http://localhost:5174/");
  await adminPage.getByPlaceholder("管理员密钥").fill(ADMIN_API_KEY);
  await adminPage.getByRole("button", { name: "进入" }).click();
  await adminPage.getByRole("button", { name: "用户" }).click();

  const userRow = adminPage.locator("li", { hasText: username });
  await expect(userRow).toBeVisible();
  await expect(userRow.getByText("正常")).toBeVisible();

  await userRow.getByRole("button", { name: "封号" }).click();
  await expect(userRow.getByText("已封禁")).toBeVisible();

  await page.goto("/");
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码").fill("password123");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByText("账号已被封禁")).toBeVisible();

  await userRow.getByRole("button", { name: "解封" }).click();
  await expect(userRow.getByText("正常")).toBeVisible();

  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码").fill("password123");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByPlaceholder("给智能体发消息")).toBeVisible();

  await userRow.getByRole("button", { name: "删除" }).click();
  await expect(userRow.getByText("已删除")).toBeVisible();
  await expect(userRow.getByRole("button", { name: "封号" })).not.toBeVisible();
  await expect(userRow.getByRole("button", { name: "删除" })).not.toBeVisible();

  await adminPage.close();
});
