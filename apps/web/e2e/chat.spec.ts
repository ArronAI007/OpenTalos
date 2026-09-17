import { test, expect } from "@playwright/test";
import { readFixtureApiKey } from "./fixtures.js";

test.beforeEach(async ({ page }) => {
  const apiKey = readFixtureApiKey();
  await page.addInitScript((key) => {
    window.localStorage.setItem("opentalos-api-key", key);
  }, apiKey);
});

test("send a message, see trace events stream in, approve the HITL pause, see completion", async ({ page }) => {
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
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

test("approving a tool-using reply works directly from the 对话 tab, without switching to 轨迹", async ({ page }) => {
  // Regression coverage for the "运行中…" dead-end: previously, a paused-for-approval run only
  // ever surfaced its 批准/拒绝 controls on the 轨迹 tab — the 对话 tab just showed a disabled
  // composer with the misleading "运行中…" label, with no visible way to unblock it.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });

  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  // Stay on the 对话 tab (the default) — do NOT click into 轨迹 for this test.
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("等待你确认")).toBeVisible();

  await approveButton.click();

  await expect(page.getByText(/根据查询结果/)).toBeVisible({ timeout: 10_000 });
  // Only the textarea's enabled-ness reflects "composer usable again" here — 发送 also requires a
  // non-empty draft (see ChatPanel's `disabled={disabled || !draft.trim()}`), which is correctly
  // still empty right after sending, independent of run status.
  await expect(chatInput).toBeEnabled();
});

test("pressing Enter to confirm an IME composition fills the textarea instead of sending", async ({ page }) => {
  // Regression coverage: typing via an IME (e.g. Chinese pinyin) and pressing Enter to confirm a
  // candidate was previously treated identically to a real Enter keypress -- submitting whatever
  // partial/incorrect text was in the composer at that moment, instead of just completing the
  // composition. `isComposing: true` on the keydown event is what a real IME sets in this case.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sentMessage = page.locator("li.message-user", { hasText: "测试" });

  await chatInput.fill("测试");
  await chatInput.dispatchEvent("keydown", { key: "Enter", isComposing: true });

  await expect(chatInput).toHaveValue("测试");
  await expect(sentMessage).not.toBeVisible();

  // A real Enter afterward (composition over) still sends normally.
  await chatInput.dispatchEvent("keydown", { key: "Enter", isComposing: false });
  await expect(sentMessage).toBeVisible();
});

test("the header shows a centered title with a fixed caption, and 轨迹 is a toggle icon (no 对话 tab)", async ({
  page,
}) => {
  await page.goto("/");

  // No "对话" tab exists anymore -- 对话 is just the default view.
  await expect(page.getByRole("button", { name: "对话", exact: true })).toHaveCount(0);

  await expect(page.getByText("AI 生成可能有误，注意核实")).toBeVisible();

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  const traceToggle = page.getByRole("button", { name: "轨迹" });
  await expect(traceToggle).toHaveAttribute("aria-pressed", "false");
  await traceToggle.click();
  await expect(traceToggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /tool_call_start/ })).toBeVisible({ timeout: 10_000 });

  // Click the SAME button again to toggle back -- there is no separate "对话" button anymore.
  await traceToggle.click();
  await expect(traceToggle).toHaveAttribute("aria-pressed", "false");
  await expect(chatInput).toBeVisible();
});

test("the content area extends to app-main's true edge instead of stopping at a centered 960px column", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto("/");

  const rects = await page.evaluate(() => {
    const main = document.querySelector(".app-main")!.getBoundingClientRect();
    const list = document.querySelector(".chat-empty, .message-list")!.getBoundingClientRect();
    return { appMainRight: main.right, contentRight: list.right };
  });
  // A 960px-column design would leave a large gap here on a 1440px-wide viewport (minus the 240px
  // sidebar, that's ~1200px available -- a 960px cap leaves ~120px unused on each side). Full-bleed
  // means the content element's own right edge should sit right at app-main's right edge, same as
  // .message-list already does for scrollbar placement (see the 2026-09-16 scrollbar fix).
  expect(Math.abs(rects.contentRight - rects.appMainRight)).toBeLessThan(1);
});

test("dragging the sidebar's resize handle changes and persists its width, clamped, and ignored while collapsed", async ({
  page,
}) => {
  await page.goto("/");

  const sidebar = page.locator(".session-sidebar");
  const handle = page.locator(".sidebar-resize-handle");

  const before = await sidebar.evaluate((el) => el.getBoundingClientRect().width);
  expect(Math.round(before)).toBe(240);

  const box = await handle.boundingBox();
  if (!box) throw new Error("resize handle not found");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 100, box.y + box.height / 2, { steps: 5 });
  await page.mouse.up();

  const after = await sidebar.evaluate((el) => el.getBoundingClientRect().width);
  expect(after).toBeGreaterThan(before + 50);

  // Persisted (see lib/sidebar-width.ts) -- a reload restores the dragged width.
  const stored = await page.evaluate(() => localStorage.getItem("opentalos-sidebar-width"));
  expect(Number(stored)).toBeCloseTo(after, 0);
  await page.reload();
  const afterReload = await sidebar.evaluate((el) => el.getBoundingClientRect().width);
  expect(Math.round(afterReload)).toBe(Math.round(after));

  // Clamped to MAX_SIDEBAR_WIDTH even when dragged far past it.
  const box2 = await handle.boundingBox();
  if (!box2) throw new Error("resize handle not found");
  await page.mouse.move(box2.x + box2.width / 2, box2.y + box2.height / 2);
  await page.mouse.down();
  await page.mouse.move(box2.x + 2000, box2.y + box2.height / 2, { steps: 5 });
  await page.mouse.up();
  const clamped = await sidebar.evaluate((el) => el.getBoundingClientRect().width);
  expect(clamped).toBeLessThanOrEqual(420);

  // Collapsing ignores the dragged width entirely -- fixed at 56px (see .session-sidebar-collapsed
  // in app.css). Waits past the 300ms width transition (see .session-sidebar's own `transition`)
  // so this reads the fully-settled value, not a mid-animation one.
  await page.getByRole("button", { name: "收起侧栏" }).click();
  await page.waitForTimeout(400);
  const collapsedWidth = await sidebar.evaluate((el) => el.getBoundingClientRect().width);
  expect(Math.round(collapsedWidth)).toBe(56);
});

test("sending a message while the model is actively streaming steers it instead of being blocked", async ({ page }) => {
  // MODEL_PROVIDER=mock's complete() always calls lookup_exchange_rate on round 1 for any
  // first-turn message when a tool is registered, then narrates the tool result on round 2 with a
  // 120ms-per-chunk streamed reply (see mock.ts) -- round 2's streaming window is what this test
  // steers during.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  // Wait for round 2's streaming to actually begin (composer no longer force-disabled the moment
  // any reply text is visible), then send a second message -- this must steer, not queue/block.
  await expect(page.locator(".message-streaming")).toBeVisible({ timeout: 10_000 });
  await expect(chatInput).toBeEnabled();
  await chatInput.fill("请用英文回复");
  await sendButton.click();

  await expect(page.getByText(/已发送/)).toBeVisible({ timeout: 5_000 });

  // The run must still complete normally afterward (approve the HITL pause it already required
  // before steering was ever involved) -- steering doesn't skip the existing approval gate.
  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();
  await expect(page.locator("li.message-assistant").last()).not.toBeEmpty({ timeout: 10_000 });
});

test("sending a message while paused for approval queues it as a follow-up, sent automatically once the run finishes", async ({ page }) => {
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  // Do NOT approve yet -- the run is "paused". Go back to 对话 and send a real follow-up while
  // still paused, the way an actual user would (this only works once this task's App.tsx change
  // stops disabling the composer during "paused", not just "running" as Task 8 left it).
  await page.getByRole("button", { name: "轨迹" }).click();

  await expect(chatInput).toBeEnabled();
  await chatInput.fill("这是一条排队消息");
  await sendButton.click();

  const queuedBubble = page.locator("li.message-user", { hasText: "这是一条排队消息" });
  // Queued, not yet sent to the server: no new user bubble yet, and the run is still paused.
  await expect(queuedBubble).not.toBeVisible();

  await page.getByRole("button", { name: /轨迹/ }).click();
  await approveButton.click();

  await expect(queuedBubble).toBeVisible({ timeout: 10_000 });
});

test("multiple messages queued while paused drain strictly one at a time, in order", async ({ page }) => {
  // Regression coverage for a race found in code review: dequeuing item N used to re-trigger the
  // drain effect before item N's own send had settled, so item N+1 could start concurrently
  // instead of waiting for item N's own run (and, here, its own pause) to resolve first.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "轨迹" }).click();

  await expect(chatInput).toBeEnabled();
  await chatInput.fill("排队消息一");
  await sendButton.click();
  await chatInput.fill("排队消息二");
  await sendButton.click();

  const bubbleOne = page.locator("li.message-user", { hasText: "排队消息一" });
  const bubbleTwo = page.locator("li.message-user", { hasText: "排队消息二" });
  await expect(bubbleOne).not.toBeVisible();
  await expect(bubbleTwo).not.toBeVisible();

  // Approve the original pause -- this drains queued message #1, which (via the mock provider's
  // tool call) pauses again itself. #2 must NOT be sent yet: it's still waiting behind #1.
  await page.getByRole("button", { name: /轨迹/ }).click();
  await approveButton.click();

  await expect(bubbleOne).toBeVisible({ timeout: 10_000 });
  await expect(bubbleTwo).not.toBeVisible();

  // Approve message #1's own pause -- only now should #2 finally drain and get sent.
  await page.getByRole("button", { name: /轨迹/ }).click();
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();

  await expect(bubbleTwo).toBeVisible({ timeout: 10_000 });
});

test("a drained follow-up that fails to send doesn't permanently stick the queue", async ({ page }) => {
  // Regression coverage: the drain effect's re-entrancy guard used to be released only once
  // hasActiveRun transitioned true->false -- which never happens if a drained item's own startRun
  // call fails (no run ever becomes active), leaving the guard stuck forever and freezing every
  // later queued item. handleSend now reports success/failure so the drain effect can release the
  // guard immediately on failure too.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "轨迹" }).click();

  await expect(chatInput).toBeEnabled();
  await chatInput.fill("会发送失败的排队消息");
  await sendButton.click();
  await chatInput.fill("应该仍能送达的排队消息");
  await sendButton.click();

  // Fail only the NEXT POST /runs -- i.e. the first queued item's own startRun call once drained
  // (the original message's startRun already completed before this route is registered).
  let postCount = 0;
  await page.route("**/runs?*", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    postCount += 1;
    if (postCount === 1) return route.fulfill({ status: 500, body: "{}" });
    return route.continue();
  });

  await page.getByRole("button", { name: /轨迹/ }).click();
  await approveButton.click();

  const secondBubble = page.locator("li.message-user", { hasText: "应该仍能送达的排队消息" });
  await expect(secondBubble).toBeVisible({ timeout: 10_000 });
});

test("shows a loading spinner while a file is being read, then the real preview, inside the composer box", async ({
  page,
}) => {
  // Slows FileReader down so the intermediate "loading" state (see PendingAttachment.status in
  // lib/attachments.ts) is reliably observable instead of racing past it — a real file this small
  // would otherwise read near-instantly, making the loading chip flash too briefly to assert on.
  await page.addInitScript(() => {
    const OriginalFileReader = window.FileReader;
    class SlowFileReader extends OriginalFileReader {
      readAsDataURL(blob: Blob) {
        setTimeout(() => super.readAsDataURL(blob), 500);
      }
      readAsText(blob: Blob) {
        setTimeout(() => super.readAsText(blob), 500);
      }
    }
    // @ts-expect-error test-only override to simulate a slow file read
    window.FileReader = SlowFileReader;
  });

  await page.goto("/");

  const onePixelPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  );
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles({ name: "cat.png", mimeType: "image/png", buffer: onePixelPng });

  const spinner = page.locator(".attachment-chip-spinner");
  await expect(spinner).toBeVisible();

  // Sending while an attachment is still loading would inline `undefined` into the outgoing
  // message (dataUrl/textContent only exist once it's ready) — the send button must stay disabled.
  const sendButton = page.getByRole("button", { name: "发送" });
  await expect(sendButton).toBeDisabled();

  const chip = page.locator(".attachment-chip", { hasText: "cat.png" });
  await expect(chip.locator("img.attachment-chip-thumb")).toBeVisible({ timeout: 3000 });
  await expect(spinner).not.toBeVisible();
  await expect(sendButton).toBeEnabled();

  // The preview list must be nested INSIDE the bordered composer box, not floating above it.
  const isInsideComposer = await page.evaluate(() => {
    const list = document.querySelector(".attachment-preview-list");
    const composer = document.querySelector(".composer");
    return !!list && !!composer && composer.contains(list);
  });
  expect(isInsideComposer).toBe(true);
});

test("attaching an image previews it, sends it with the message, and shows it in the sent bubble", async ({ page }) => {
  // A minimal valid 1x1 transparent PNG — small enough to stay well under every size cap this
  // feature enforces, real enough for the browser to actually decode and render as an <img>.
  const onePixelPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  );

  await page.goto("/");

  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles({ name: "cat.png", mimeType: "image/png", buffer: onePixelPng });

  // Preview chip appears inside the composer box, above the textarea, before sending.
  const chip = page.locator(".attachment-chip", { hasText: "cat.png" });
  await expect(chip).toBeVisible();

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  // Sending must work even with an empty draft, as long as there's an attachment.
  await expect(sendButton).toBeEnabled();
  await chatInput.fill("这张图里有什么？");
  await sendButton.click();

  // The preview chip is gone once sent (attachments were consumed into the message).
  await expect(chip).not.toBeVisible();

  const sentBubble = page.locator("li.message-user");
  await expect(sentBubble.locator(".message-image")).toBeVisible();
  await expect(sentBubble).toContainText("这张图里有什么？");

  // MODEL_PROVIDER=mock's tool round pauses for approval before replying — approve it, then check
  // the final reply acknowledges the image (see mock.ts's imageNote).
  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();
  await expect(page.getByText(/收到 1 张图片/)).toBeVisible({ timeout: 10_000 });
});

test("attaching a text file shows only a filename chip in the sent bubble, but still inlines its content into the message sent to the model", async ({
  page,
}) => {
  await page.goto("/");

  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles({
    name: "notes.py",
    mimeType: "text/x-python",
    buffer: Buffer.from("print('hello from attachment')"),
  });

  const chip = page.locator(".attachment-chip", { hasText: "notes.py" });
  await expect(chip).toBeVisible();

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("这个文件是干什么的？");
  await sendButton.click();

  const sentBubble = page.locator("li.message-user");
  // The typed text and a compact filename+type chip both render — but neither the raw
  // "[附件: notes.py] ```...```" wrapping used for the model, nor the file's actual content, is
  // ever shown in the sent bubble (see TextAttachmentChip: filename only, by design).
  await expect(sentBubble).toContainText("这个文件是干什么的？");
  await expect(sentBubble).not.toContainText("[附件: notes.py]");
  await expect(sentBubble.locator(".text-attachment-chip-name")).toContainText("notes.py");
  await expect(sentBubble.locator(".text-attachment-chip-type")).toContainText("PY");
  await expect(sentBubble).not.toContainText("print('hello from attachment')");

  // The mock model still sees the file content inlined into what was actually sent — approve the
  // HITL pause and confirm the reply references it (mock.ts echoes back the last tool result, not
  // this content directly, so just confirm the run actually completes normally).
  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();
  await expect(page.locator("li.message-assistant").last()).not.toBeEmpty({ timeout: 10_000 });
});

test("removing a pending attachment before sending drops it from the message", async ({ page }) => {
  await page.goto("/");

  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("should not be sent"),
  });

  const chip = page.locator(".attachment-chip", { hasText: "notes.txt" });
  await expect(chip).toBeVisible();
  await chip.getByRole("button", { name: /移除附件/ }).click();
  await expect(chip).not.toBeVisible();

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("普通消息，没有附件");
  await sendButton.click();

  const sentBubble = page.locator("li.message-user");
  await expect(sentBubble).toContainText("普通消息，没有附件");
  await expect(sentBubble).not.toContainText("should not be sent");
});

test("clicking stop mid-stream cancels the model call and the composer recovers", async ({ page }) => {
  // NOTE: MODEL_PROVIDER=mock's complete() (packages/model-providers/src/mock.ts) calls
  // lookup_exchange_rate on round 1 for ANY first-turn message whenever a tool is registered --
  // it never inspects message content -- and chat-agent's registry always registers that tool
  // (packages/chat-agent/src/registry.ts). Round 1 never streams any text (it goes straight from
  // nothing to a tool_call chunk), so the stop control (gated on non-empty streamingText) can only
  // ever become visible during round 2 (narrating the tool result). This means a browser-driven
  // run under this stack can never reach "done" directly via cancellation the way a tool-free
  // turn would -- a tool was already called before the cancel took effect, so the graph still
  // requires approval afterward. That direct "cancel a plain reply straight to done, no tool
  // involved" path IS covered, at the unit level, by chat-agent's own test suite (see
  // packages/chat-agent/src/index.test.ts's "returns the partial reply and skips HITL approval
  // when the signal is aborted mid-stream" test, which uses a custom ModelProvider that never
  // calls a tool). This e2e test instead verifies the part only a real browser round-trip can
  // prove: clicking 停止 actually reaches the backend and the UI recovers to a working state
  // afterward, rather than hanging.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });

  let cancelRequestCount = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/cancel")) {
      cancelRequestCount += 1;
    }
  });

  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  const stopButton = page.getByRole("button", { name: "停止" });
  await expect(stopButton).toBeVisible({ timeout: 10_000 });
  await stopButton.click();

  expect(cancelRequestCount).toBe(1);

  // A tool was already called before the cancel took effect, so the graph still routes through
  // confirm/paused -- cancelling the model's narration doesn't undo a real tool side-effect.
  // This is correct: only the model's own streaming phase is cancellable, per the design's
  // non-goal, and a prior tool call is unaffected by cancelling the text that narrates it.
  await page.getByRole("button", { name: /轨迹/ }).click();
  const approveButton = page.getByRole("button", { name: "✓ 批准" });
  await expect(approveButton).toBeVisible({ timeout: 10_000 });
  await approveButton.click();

  await expect(chatInput).toBeEnabled({ timeout: 10_000 });
  await expect(sendButton).toBeEnabled();
  await expect(page.locator(".message-assistant").last()).not.toBeEmpty();
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

  // At desktop viewport width (Playwright's default), the session sidebar is permanently docked
  // and its "☰" mobile toggle is display:none (so not focusable) — meaning the sidebar's own
  // controls (collapse button, "+ 新会话", the workspace toolbar's search/sort/new icons, then the
  // one default session, then "设置") are the genuinely first focusable elements on the page,
  // ahead of the header's Session log button, the 轨迹 toggle, and the chat input.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "收起侧栏" })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "+ 新会话" })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "搜索会话" })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "按最早优先排序" })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "新建会话" })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "新会话", exact: true })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "设置", exact: true })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /Session log/ })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "轨迹" })).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(page.getByPlaceholder("给智能体发消息")).toBeFocused();
});

test("double-clicking 批准 does not enqueue a duplicate resume request (Fix 4)", async ({ page }) => {
  // Regression test: timeline.status stays "paused" for up to ~500ms after the first click
  // (until the next SSE poll cycle reports the status change), so two clicks fired in the same
  // JS tick -- before React has re-rendered the button as disabled -- could both call onApprove
  // and enqueue two "resume" tasks for the same run. The fix guards the click handler itself
  // (`if (hasResponded) return`) rather than relying solely on the disabled attribute, since the
  // DOM hasn't necessarily been updated yet at the moment of a same-tick double click.
  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
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

test("a stale runId with no matching checkpoint recovers silently instead of showing a connection-lost error", async ({
  page,
}) => {
  // Regression coverage: opening the app with a session (from localStorage) whose runId points at
  // a checkpoint that no longer exists server-side (e.g. deleted, or from a wiped dev database —
  // this genuinely happened once) previously showed "与服务器的连接已断开，请刷新页面重试" — a
  // message a refresh can never fix, since the same stale runId just gets reloaded and retried,
  // failing identically forever. It should instead recover silently: the composer stays usable,
  // and the earlier message text is still visible.
  const staleSession = {
    id: "stale-session-1",
    createdAt: Date.now(),
    runId: "does-not-exist-anymore",
    messages: [{ id: "m1", role: "user", text: "旧消息，对应的 run 已经不存在了", runId: "does-not-exist-anymore" }],
  };
  await page.addInitScript((session) => {
    window.localStorage.setItem("opentalos-sessions", JSON.stringify([session]));
    window.localStorage.setItem("opentalos-active-session", session.id);
  }, staleSession);

  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });

  await expect(page.getByRole("region", { name: "对话" }).getByText("旧消息，对应的 run 已经不存在了")).toBeVisible();
  await expect(chatInput).toBeEnabled({ timeout: 10_000 });
  await expect(sendButton).toBeVisible();
  await expect(page.getByText(/连接已断开/)).not.toBeVisible();
});

test("a stale runId belonging to a different tenant (e.g. after switching API keys) also recovers silently", async ({
  page,
}) => {
  // Regression coverage: entering a different API key (a different tenant) while a session's
  // runId still pointed at a run created under the PREVIOUS key returned 403 (not 404) from
  // GET /runs/:runId -- a case the original stale-runId fix didn't cover, so it fell through to
  // the same misleading "与服务器的连接已断开，请刷新页面重试" as a real connectivity failure,
  // even though everything actually still worked fine for new messages.
  const adminHeaders = { Authorization: "Bearer e2e-admin-key", "Content-Type": "application/json" };

  const tenantAResponse = await page.request.post("http://localhost:3001/admin/tenants", {
    headers: adminHeaders,
    data: { name: `tenant-a-${Date.now()}` },
  });
  const tenantA = await tenantAResponse.json();
  const tenantAKeyResponse = await page.request.post(`http://localhost:3001/admin/tenants/${tenantA.id}/api-keys`, {
    headers: adminHeaders,
  });
  const { rawKey: tenantAKey } = await tenantAKeyResponse.json();

  const runResponse = await page.request.post("http://localhost:3001/runs?sessionId=cross-tenant-session", {
    headers: { Authorization: `Bearer ${tenantAKey}`, "Content-Type": "application/json" },
    data: { message: "tenant A 的消息" },
  });
  const { runId: tenantARunId } = await runResponse.json();

  const tenantBResponse = await page.request.post("http://localhost:3001/admin/tenants", {
    headers: adminHeaders,
    data: { name: `tenant-b-${Date.now()}` },
  });
  const tenantB = await tenantBResponse.json();
  const tenantBKeyResponse = await page.request.post(`http://localhost:3001/admin/tenants/${tenantB.id}/api-keys`, {
    headers: adminHeaders,
  });
  const { rawKey: tenantBKey } = await tenantBKeyResponse.json();

  // Simulate: the browser now has tenant B's key active (as if the user just re-entered a
  // different API key), but the session it was last looking at still references tenant A's run.
  const staleSession = {
    id: "cross-tenant-session",
    createdAt: Date.now(),
    runId: tenantARunId,
    messages: [{ id: "m1", role: "user", text: "tenant A 的消息", runId: tenantARunId }],
  };
  await page.addInitScript(
    ({ key, session }) => {
      window.localStorage.setItem("opentalos-api-key", key);
      window.localStorage.setItem("opentalos-sessions", JSON.stringify([session]));
      window.localStorage.setItem("opentalos-active-session", session.id);
    },
    { key: tenantBKey, session: staleSession },
  );

  await page.goto("/");

  const chatInput = page.getByPlaceholder("给智能体发消息");
  await expect(chatInput).toBeEnabled({ timeout: 10_000 });
  await expect(page.getByText(/连接已断开/)).not.toBeVisible();
});

test("a terminal SSE connection failure re-enables sending a new message (Fix 5)", async ({ page }) => {
  // Regression test: isRunInFlight was computed purely from timeline.status, which never
  // advances to "done" if the SSE connection dies terminally (no more events or status changes
  // can ever arrive) -- permanently locking the send button/input with no recovery path. Forcing
  // the very first GET to /runs/:runId/events to fail with a non-200 status makes EventSource
  // "fail the connection" per spec (no auto-retry, readyState CLOSED), which is exactly the
  // terminal-failure case useRunEvents' connectionError flag exists to detect.
  await page.route("**/events*", (route) => route.fulfill({ status: 500, body: "" }));

  await page.goto("/");
  const chatInput = page.getByPlaceholder("给智能体发消息");
  const sendButton = page.getByRole("button", { name: "发送" });
  await chatInput.fill("今天美元兑人民币汇率是多少？");
  await sendButton.click();

  // The mocked 500 response can fail the EventSource almost immediately, so whether the input
  // was ever observably disabled is racy and not the point of this test -- what matters is that,
  // once the connection is confirmed dead, sending recovers instead of staying locked forever.
  await expect(page.getByText(/连接已断开/)).toBeVisible({ timeout: 10_000 });
  await expect(chatInput).toBeEnabled();
  await expect(sendButton).toBeEnabled();
});
