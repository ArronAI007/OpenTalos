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

  // The header's "轨迹" (trace drawer) toggle button precedes the chat input in DOM/tab order
  // (see App.tsx: <header> renders before <ChatPanel>), so it is the genuinely first focusable
  // element on the page. Confirm that, then confirm the second Tab press reaches the chat input.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /轨迹/ })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByPlaceholder("输入消息…")).toBeFocused();
});

test("closed trace drawer's buttons are not keyboard-reachable, but open ones are (Fix 3)", async ({ page }) => {
  await page.goto("/");

  // Regression test: TraceDrawer sets aria-hidden={!open} on the closed drawer, but its CSS only
  // hid it visually (transform/opacity/pointer-events) without visibility: hidden, so its close
  // button stayed in the tab order even while aria-hidden="true" -- a WCAG aria-hidden-focus
  // violation. The trace-drawer (and its close button) is rendered AFTER the chat panel in the
  // DOM (see App.tsx), so continuing to Tab past the send button is what would have reached it.
  await page.keyboard.press("Tab"); // 轨迹 trigger
  await page.keyboard.press("Tab"); // chat input
  await expect(page.getByPlaceholder("输入消息…")).toBeFocused();
  await page.keyboard.press("Tab"); // send button
  await expect(page.getByRole("button", { name: "发送" })).toBeFocused();

  const drawer = page.locator(".trace-drawer");
  const drawerClose = page.locator(".trace-drawer-close");
  await expect(drawer).toHaveAttribute("aria-hidden", "true");
  await expect(drawer).toHaveCSS("visibility", "hidden");

  await page.keyboard.press("Tab");
  await expect(drawerClose).not.toBeFocused();

  // Opening the drawer must still show the slide-in animation (no snapping to the open state)
  // and make its buttons genuinely tabbable again.
  const transitionDuration = await drawer.evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(transitionDuration).not.toBe("0s");

  await page.getByRole("button", { name: /轨迹/ }).click();
  await expect(drawer).toHaveClass(/trace-drawer-open/);
  await expect(drawer).toHaveAttribute("aria-hidden", "false");
  await expect(drawer).toHaveCSS("visibility", "visible");

  await drawerClose.focus();
  await expect(drawerClose).toBeFocused();
});

test("double-clicking 批准 does not enqueue a duplicate resume request (Fix 4)", async ({ page }) => {
  // Regression test: timeline.status stays "paused" for up to ~500ms after the first click
  // (until the next SSE poll cycle reports the status change), so two clicks fired in the same
  // JS tick -- before React has re-rendered the button as disabled -- could both call onApprove
  // and enqueue two "resume" tasks for the same run. The fix guards the click handler itself
  // (`if (hasResponded) return`) rather than relying solely on the disabled attribute, since the
  // DOM hasn't necessarily been updated yet at the moment of a same-tick double click.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("输入消息…");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });

  let resumeRequestCount = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/resume")) {
      resumeRequestCount += 1;
    }
  });

  // Two synchronous .click() calls within a single page.evaluate() dispatch both click events in
  // the same JS turn, before any React re-render can flip the `disabled` attribute -- this is
  // what actually races the click handler's own guard, unlike two separate Playwright round trips
  // (which give React ample time to disable the button between them).
  await approveButton.evaluate((el: HTMLButtonElement) => {
    el.click();
    el.click();
  });

  await expect(approveButton).toBeDisabled();
  await expect(page.getByText(/根据查询结果/)).toBeVisible({ timeout: 10_000 });

  expect(resumeRequestCount).toBe(1);
});
