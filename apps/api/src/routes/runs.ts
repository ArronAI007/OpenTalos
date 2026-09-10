import type { FastifyInstance } from "fastify";
import { randomUUID } from "node:crypto";
import type { ChatState } from "@opentalos/example-chat-demo-agent";
import type { ServerDeps } from "../server.js";
import { DEV_TENANT_ID } from "../dev-tenant.js";

interface StartRunBody {
  message?: string;
}

interface ResumeRunBody {
  approved?: boolean;
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

    const runId = randomUUID();
    const initialState: ChatState = { message };
    await scheduler.enqueueStart("chat-demo-agent", initialState, { tenantId: DEV_TENANT_ID, sessionId }, runId);
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
    if (checkpoint.tenantId !== DEV_TENANT_ID || checkpoint.sessionId !== sessionId) {
      return reply.code(403).send({ error: "Run belongs to a different session" });
    }
    return reply.send({ runId: checkpoint.runId, status: checkpoint.status, state: checkpoint.state });
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
          { tenantId: DEV_TENANT_ID, sessionId },
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
    if (checkpoint.tenantId !== DEV_TENANT_ID || checkpoint.sessionId !== sessionId) {
      return reply.code(403).send({ error: "Run belongs to a different session" });
    }

    reply.hijack();
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });

    const lastEventIdHeader = request.headers["last-event-id"];
    const rawCursor = Array.isArray(lastEventIdHeader) ? lastEventIdHeader[0] : lastEventIdHeader;
    let cursor = rawCursor ? Number(rawCursor) : 0;
    if (Number.isNaN(cursor)) cursor = 0;

    let lastStatus: string | undefined;
    let stopped = false;

    const poll = async () => {
      if (stopped) return;
      try {
        const events = await deps.listEventsSince(runId, cursor);
        for (const event of events) {
          cursor = event.id;
          reply.raw.write(`id: ${event.id}\nevent: trace\ndata: ${JSON.stringify(event)}\n\n`);
        }
        const current = await checkpointStore.load(runId);
        if (current && current.status !== lastStatus) {
          lastStatus = current.status;
          reply.raw.write(`event: status_changed\ndata: ${JSON.stringify({ status: current.status })}\n\n`);
          if (current.status === "done") {
            reply.raw.write(`event: done\ndata: {}\n\n`);
            stopped = true;
            clearInterval(timer);
            reply.raw.end();
          }
        }
      } catch (error) {
        // A polling-cycle DB error is logged and retried next tick — must not crash the gateway
        // process nor terminate the SSE stream over a transient hiccup, matching the convention
        // already used in Worker.pollOnce().
        console.error(`SSE poll failed for run "${runId}": ${error instanceof Error ? error.message : String(error)}`);
      }
    };

    const timer = setInterval(poll, 500);
    void poll();

    request.raw.on("close", () => {
      stopped = true;
      clearInterval(timer);
    });
  });
}
