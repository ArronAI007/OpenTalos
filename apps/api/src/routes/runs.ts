import type { FastifyInstance } from "fastify";
import { randomUUID } from "node:crypto";
import type { ServerResponse } from "node:http";
import type { ChatState } from "@opentalos/chat-agent";
import type { ServerDeps } from "../server.js";
import { requireTenantId } from "../auth.js";

/** Every currently-open SSE response, tracked so graceful shutdown can end them proactively.
 * Without this, a hijacked SSE response stays open until its run finishes or the client
 * disconnects, which would make `app.close()` hang forever during shutdown. */
const activeSseConnections = new Set<ServerResponse>();

/** Ends every currently-open SSE response immediately. Called during graceful shutdown so
 * app.close() doesn't hang waiting for long-lived hijacked SSE streams that would otherwise
 * only end when their run completes or the client disconnects. */
export function closeAllSseConnections(): void {
  for (const res of activeSseConnections) {
    res.end();
  }
  activeSseConnections.clear();
}

/** Test-only seam: the number of SSE responses currently tracked for shutdown. Exposed so tests
 * can assert the route handler registers/unregisters `reply.raw` at the right points without
 * reaching into module-private state directly. */
export function getActiveSseConnectionCountForTests(): number {
  return activeSseConnections.size;
}

interface StartRunBody {
  message?: string;
  images?: string[];
}

// Text attachments (see apps/web's ChatPanel) are merged into `message` client-side before it
// ever reaches this route, so this cap bounds both a pasted essay and a few merged text files at
// once — not just what a human would type by hand.
const MAX_MESSAGE_LENGTH = 200_000;
const MAX_IMAGES_PER_MESSAGE = 4;
// ~4.5MB decoded (base64 inflates by ~4/3) — generous headroom for a phone photo, well under
// buildServer's 20MB Fastify bodyLimit even with MAX_IMAGES_PER_MESSAGE of them in one request.
const MAX_IMAGE_DATA_URI_BYTES = 6 * 1024 * 1024;

/** Returns a human-readable validation error, or undefined if `images` is absent or valid. */
function validateImages(images: unknown): string | undefined {
  if (images === undefined) return undefined;
  if (!Array.isArray(images)) return "images must be an array of data URI strings";
  if (images.length > MAX_IMAGES_PER_MESSAGE) {
    return `at most ${MAX_IMAGES_PER_MESSAGE} images are allowed per message`;
  }
  for (const image of images) {
    if (typeof image !== "string" || !image.startsWith("data:image/")) {
      return 'each image must be a "data:image/...;base64,..." URI string';
    }
    if (Buffer.byteLength(image, "utf8") > MAX_IMAGE_DATA_URI_BYTES) {
      return `each image must be under ${Math.floor(MAX_IMAGE_DATA_URI_BYTES / (1024 * 1024))}MB`;
    }
  }
  return undefined;
}

interface ResumeRunBody {
  approved?: boolean;
}

interface SteerRunBody {
  message?: string;
}

interface SessionQuery {
  sessionId?: string;
}

export function registerRunRoutes(app: FastifyInstance, deps: ServerDeps): void {
  const { checkpointStore, scheduler } = deps;

  app.post<{ Body: StartRunBody; Querystring: SessionQuery }>("/runs", async (request, reply) => {
    const sessionId = request.query.sessionId;
    if (!sessionId) {
      return reply.code(400).send({ error: "sessionId query parameter is required" });
    }
    const message = request.body?.message;
    if (typeof message !== "string" || message.trim().length === 0) {
      return reply.code(400).send({ error: "message body field is required and must be a non-empty string" });
    }
    if (message.length > MAX_MESSAGE_LENGTH) {
      return reply.code(400).send({ error: `message must be at most ${MAX_MESSAGE_LENGTH} characters` });
    }
    const imagesError = validateImages(request.body?.images);
    if (imagesError) {
      return reply.code(400).send({ error: imagesError });
    }

    const runId = randomUUID();
    const initialState: ChatState = { message, images: request.body?.images };
    await scheduler.enqueueStart(
      "chat-agent",
      initialState,
      { tenantId: requireTenantId(request), sessionId },
      runId,
    );
    return reply.code(201).send({ runId });
  });

  app.get<{ Params: { runId: string }; Querystring: SessionQuery }>("/runs/:runId", async (request, reply) => {
    const sessionId = request.query.sessionId;
    if (!sessionId) {
      return reply.code(400).send({ error: "sessionId query parameter is required" });
    }
    const checkpoint = await checkpointStore.load(request.params.runId);
    if (!checkpoint) {
      return reply.code(404).send({ error: `Run "${request.params.runId}" not found` });
    }
    if (checkpoint.tenantId !== requireTenantId(request) || checkpoint.sessionId !== sessionId) {
      return reply.code(403).send({ error: "Run belongs to a different session" });
    }
    return reply.send({
      runId: checkpoint.runId,
      status: checkpoint.status,
      state: checkpoint.state,
      ...(checkpoint.error !== undefined ? { error: checkpoint.error } : {}),
    });
  });

  app.post<{ Params: { runId: string }; Body: ResumeRunBody; Querystring: SessionQuery }>(
    "/runs/:runId/resume",
    async (request, reply) => {
      const sessionId = request.query.sessionId;
      if (!sessionId) {
        return reply.code(400).send({ error: "sessionId query parameter is required" });
      }
      const approved = request.body?.approved;
      if (typeof approved !== "boolean") {
        return reply.code(400).send({ error: "approved body field is required and must be a boolean" });
      }
      try {
        await scheduler.enqueueResume(
          request.params.runId,
          { type: "approval", approved },
          { tenantId: requireTenantId(request), sessionId },
        );
      } catch (error) {
        const messageText = error instanceof Error ? error.message : String(error);
        if (messageText.includes("no checkpoint found")) {
          return reply.code(404).send({ error: messageText });
        }
        if (messageText.includes("different tenant")) {
          return reply.code(403).send({ error: messageText });
        }
        if (messageText.includes("is not paused")) {
          return reply.code(409).send({ error: messageText });
        }
        throw error;
      }
      return reply.code(204).send();
    },
  );

  app.post<{ Params: { runId: string }; Body: SteerRunBody; Querystring: SessionQuery }>(
    "/runs/:runId/steer",
    async (request, reply) => {
      const sessionId = request.query.sessionId;
      if (!sessionId) {
        return reply.code(400).send({ error: "sessionId query parameter is required" });
      }
      const message = request.body?.message;
      if (typeof message !== "string" || message.trim().length === 0) {
        return reply.code(400).send({ error: "message body field is required and must be a non-empty string" });
      }
      if (message.length > MAX_MESSAGE_LENGTH) {
        return reply.code(400).send({ error: `message must be at most ${MAX_MESSAGE_LENGTH} characters` });
      }
      const checkpoint = await checkpointStore.load(request.params.runId);
      if (!checkpoint) {
        return reply.code(404).send({ error: `Run "${request.params.runId}" not found` });
      }
      if (checkpoint.tenantId !== requireTenantId(request) || checkpoint.sessionId !== sessionId) {
        return reply.code(403).send({ error: "Run belongs to a different session" });
      }
      if (checkpoint.status !== "running") {
        return reply
          .code(409)
          .send({ error: `Run "${request.params.runId}" is not running (status: ${checkpoint.status})` });
      }
      await checkpointStore.requestSteer(request.params.runId, message);
      return reply.code(204).send();
    },
  );

  app.post<{ Params: { runId: string }; Querystring: SessionQuery }>(
    "/runs/:runId/cancel",
    async (request, reply) => {
      const sessionId = request.query.sessionId;
      if (!sessionId) {
        return reply.code(400).send({ error: "sessionId query parameter is required" });
      }
      const checkpoint = await checkpointStore.load(request.params.runId);
      if (!checkpoint) {
        return reply.code(404).send({ error: `Run "${request.params.runId}" not found` });
      }
      if (checkpoint.tenantId !== requireTenantId(request) || checkpoint.sessionId !== sessionId) {
        return reply.code(403).send({ error: "Run belongs to a different session" });
      }
      await checkpointStore.requestCancel(request.params.runId);
      return reply.code(204).send();
    },
  );

  app.get<{ Params: { runId: string }; Querystring: SessionQuery }>("/runs/:runId/events", async (request, reply) => {
    const sessionId = request.query.sessionId;
    if (!sessionId) {
      return reply.code(400).send({ error: "sessionId query parameter is required" });
    }
    const runId = request.params.runId;
    const checkpoint = await checkpointStore.load(runId);
    if (!checkpoint) {
      return reply.code(404).send({ error: `Run "${runId}" not found` });
    }
    if (checkpoint.tenantId !== requireTenantId(request) || checkpoint.sessionId !== sessionId) {
      return reply.code(403).send({ error: "Run belongs to a different session" });
    }

    reply.hijack();
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    activeSseConnections.add(reply.raw);

    const lastEventIdHeader = request.headers["last-event-id"];
    const rawCursor = Array.isArray(lastEventIdHeader) ? lastEventIdHeader[0] : lastEventIdHeader;
    let cursor = rawCursor ? Number(rawCursor) : 0;
    if (Number.isNaN(cursor)) cursor = 0;

    let lastStatus: string | undefined;
    let stopped = false;
    let isPolling = false;

    reply.raw.on("error", (error) => {
      // A write-after-end (e.g. two overlapping poll() calls both taking the "done" branch) or
      // any other stream-level failure must be caught here rather than left unhandled — nothing
      // else listens for 'error' on a hijacked raw response, so an uncaught one here would crash
      // the process.
      console.error(`SSE stream error for run "${runId}": ${error.message}`);
      stopped = true;
      clearInterval(timer);
      activeSseConnections.delete(reply.raw);
    });

    // Re-entrancy guard: poll() does two DB round trips before touching cursor/lastStatus, so
    // under DB latency the fixed-cadence setInterval could otherwise start a second poll() while
    // the first is still in flight, causing duplicate frames and duplicate "done" handling.
    const poll = async () => {
      if (stopped || isPolling) return;
      isPolling = true;
      try {
        const events = await deps.listEventsSince(runId, cursor);
        for (const event of events) {
          if (stopped) return;
          cursor = event.id;
          reply.raw.write(`id: ${event.id}\nevent: trace\ndata: ${JSON.stringify(event)}\n\n`);
        }
        if (stopped) return;
        const current = await checkpointStore.load(runId);
        if (stopped) return;
        if (current && current.status !== lastStatus) {
          lastStatus = current.status;
          reply.raw.write(`event: status_changed\ndata: ${JSON.stringify({ status: current.status })}\n\n`);
          if (current.status === "done") {
            // Drain any trailing events that may still be landing in the write-chain at the
            // exact moment the checkpoint flips to "done" (PostgresEventBus.emit() is
            // fire-and-forget, so a node's final trace events can still be in flight when its
            // completeNode() save resolves).
            const trailingEvents = await deps.listEventsSince(runId, cursor);
            for (const event of trailingEvents) {
              if (stopped) return;
              cursor = event.id;
              reply.raw.write(`id: ${event.id}\nevent: trace\ndata: ${JSON.stringify(event)}\n\n`);
            }
            reply.raw.write(`event: done\ndata: {}\n\n`);
            stopped = true;
            clearInterval(timer);
            reply.raw.end();
            activeSseConnections.delete(reply.raw);
          } else if (current.status === "failed") {
            // Mirror the "done" branch above: drain any trailing trace events still landing at
            // the moment the checkpoint flips to "failed", then tell the client the run failed
            // (with the underlying error message) and close the stream — otherwise the client
            // would poll forever, since status only ever leaves "running" via "done" or "failed".
            const trailingEvents = await deps.listEventsSince(runId, cursor);
            for (const event of trailingEvents) {
              if (stopped) return;
              cursor = event.id;
              reply.raw.write(`id: ${event.id}\nevent: trace\ndata: ${JSON.stringify(event)}\n\n`);
            }
            reply.raw.write(`event: failed\ndata: ${JSON.stringify({ error: current.error ?? "模型调用失败，请重试" })}\n\n`);
            stopped = true;
            clearInterval(timer);
            reply.raw.end();
            activeSseConnections.delete(reply.raw);
          }
        }
      } catch (error) {
        // A polling-cycle DB error is logged and retried next tick — must not crash the gateway
        // process nor terminate the SSE stream over a transient hiccup, matching the convention
        // already used in Worker.pollOnce().
        console.error(`SSE poll failed for run "${runId}": ${error instanceof Error ? error.message : String(error)}`);
      } finally {
        isPolling = false;
      }
    };

    // 150ms (was 500ms): with llm_text_delta trace events now streaming the model's reply in as
    // it generates, a slower poll cadence made the "streaming" effect visibly chunky/laggy.
    const timer = setInterval(poll, 150);
    void poll();

    request.raw.on("close", () => {
      stopped = true;
      clearInterval(timer);
      activeSseConnections.delete(reply.raw);
    });
  });
}
