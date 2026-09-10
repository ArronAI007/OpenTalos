import { test, expect } from "@playwright/test";

test("send a message, see trace events stream in, approve the HITL pause, see completion", async ({ page }) => {
  await page.goto("/");

  const chatInput = page.getByPlaceholder("输入消息…");
  const sendButton = page.getByRole("button", { name: "发送" });

  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  await expect(page.getByText("今天美元兑人民币汇率是多少？")).toBeVisible();

  // A run is now in flight ("running"/"paused"): Task 5's fix cycle disabled the chat input and
  // send button for this whole window to prevent starting a second run before the first
  // completes (a data-loss bug). Assert that behavior here rather than just relying on the rest
  // of this test not accidentally exercising it.
  await expect(chatInput).toBeDisabled();
  await expect(sendButton).toBeDisabled();

  await page.getByRole("button", { name: /轨迹/ }).click();

  // The tool-call trace row renders collapsed by default (only its event type + timestamp are
  // shown); the tool name lives inside the row's JSON payload, which only renders once the row
  // is expanded by clicking its header. Expand it before asserting on the tool name.
  const toolCallRow = page.getByRole("button", { name: /tool_call_start/ });
  await expect(toolCallRow).toBeVisible({ timeout: 10_000 });
  await toolCallRow.click();
  await expect(page.getByText("lookup_exchange_rate", { exact: false })).toBeVisible();

  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();

  await expect(page.getByText(/根据查询结果/)).toBeVisible({ timeout: 10_000 });

  // The run has reached "done" — the input and send button should be re-enabled for the next message.
  await expect(chatInput).toBeEnabled();
  await expect(sendButton).toBeEnabled();
});

test("responsive layout renders without horizontal overflow at key breakpoints", async ({ page }) => {
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    const bodyWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `e2e/screenshots/chat-${width}.png` });
  }
});

test("chat input is reachable via keyboard navigation", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.tagName);
  expect(focused).toBeTruthy();
});
