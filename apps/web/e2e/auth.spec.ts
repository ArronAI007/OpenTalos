import { test, expect } from "@playwright/test";

const ADMIN_API_KEY = "e2e-admin-key";
const API_BASE = "http://localhost:3001";
const ADMIN_BASE = "http://localhost:3001/admin";

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

test("admin creates a tenant and key via the browser, and the chat UI authenticates with it end-to-end", async ({
  page,
  context,
}) => {
  const adminPage = await context.newPage();
  await adminPage.goto("http://localhost:5174/");
  await adminPage.getByPlaceholder("管理员密钥").fill(ADMIN_API_KEY);
  await adminPage.getByRole("button", { name: "进入" }).click();

  await adminPage.getByPlaceholder("租户名称").fill("browser-created-tenant");
  await adminPage.getByRole("button", { name: "创建租户" }).click();
  await adminPage.getByText("browser-created-tenant").click();
  await adminPage.getByRole("button", { name: "+ 新建 API Key" }).click();

  const revealText = await adminPage.locator(".new-key-reveal div").last().textContent();
  const rawKey = revealText?.trim();
  expect(rawKey).toBeTruthy();
  await adminPage.close();

  await page.goto("/");
  await page.getByPlaceholder("API Key").fill(rawKey!);
  await page.getByRole("button", { name: "进入" }).click();

  await page.getByPlaceholder("输入消息…").fill("今天美元兑人民币汇率是多少？");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("今天美元兑人民币汇率是多少？")).toBeVisible();

  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();
  await expect(page.getByText(/根据查询结果/)).toBeVisible({ timeout: 10_000 });
});

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

test("a revoked API key is rejected by the chat UI, which asks the user to re-enter one", async ({ page }) => {
  const { tenant, rawKey } = await createTenantAndKey("revoke-e2e-tenant");
  const keysRes = await fetch(`${ADMIN_BASE}/tenants/${tenant.id}/api-keys`, {
    headers: { Authorization: `Bearer ${ADMIN_API_KEY}` },
  });
  const keys = await keysRes.json();
  await fetch(`${ADMIN_BASE}/api-keys/${keys[0].id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${ADMIN_API_KEY}` },
  });

  await page.goto("/");
  await page.getByPlaceholder("API Key").fill(rawKey);
  await page.getByRole("button", { name: "进入" }).click();
  await page.getByPlaceholder("输入消息…").fill("hello");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("密钥无效或已被吊销，请重新输入")).toBeVisible({ timeout: 5000 });
  await expect(page.getByPlaceholder("API Key")).toBeVisible();
});
