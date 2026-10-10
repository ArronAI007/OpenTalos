import { parseSseBlock, type ChatEvent } from "./chat-events";

export type SseHandler = (event: ChatEvent, id?: number) => void;

// 读 SSE 流：逐帧解析，把 (event, id) 交给回调。id 来自服务端的 `id:` 行，重连据此续传。
async function readSse(resp: Response, onEvent: SseHandler): Promise<void> {
  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status} ${detail}`.trim());
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const frame = parseSseBlock(block);
      if (frame) onEvent(frame.event, frame.id);
    }
  }
}

export async function postSse(
  url: string,
  body: unknown,
  onEvent: SseHandler,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  await readSse(resp, onEvent);
}

// 续传：GET /stream?after=N 从指定下标补发并跟随到本轮结束；无事件（运行已结束）时立即结束。
export async function getSse(url: string, onEvent: SseHandler, signal?: AbortSignal): Promise<void> {
  const resp = await fetch(url, { signal });
  await readSse(resp, onEvent);
}
