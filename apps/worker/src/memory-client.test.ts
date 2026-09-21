import { createServer, type Server } from "node:http";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  consolidateTenant,
  extractMemory,
  HttpMemoryStore,
  listMemorySummary,
  listTenantsWithPendingMemories,
} from "./memory-client.js";

let server: Server;
let lastRequest: { method?: string; url?: string; body: string } | undefined;
let responseOverride: { status: number; body?: unknown } | undefined;

beforeEach(async () => {
  lastRequest = undefined;
  responseOverride = undefined;
  server = createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      lastRequest = { method: req.method, url: req.url, body };
      const override = responseOverride ?? { status: 204 };
      res.writeHead(override.status, { "content-type": "application/json" });
      res.end(override.body === undefined ? undefined : JSON.stringify(override.body));
    });
  });
  await new Promise<void>((resolvePromise) => server.listen(0, resolvePromise));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("expected a bound TCP port");
  process.env.MEMORY_SERVICE_URL = `http://localhost:${address.port}`;
});

afterEach(async () => {
  delete process.env.MEMORY_SERVICE_URL;
  await new Promise<void>((resolvePromise) => server.close(() => resolvePromise()));
});

describe("extractMemory", () => {
  it("POSTs the conversation turn to /memory/extract", async () => {
    await extractMemory({
      tenantId: "tenant-a",
      sessionId: "s1",
      runId: "run-1",
      userMessage: "hi",
      assistantReply: "hello",
    });
    expect(lastRequest?.method).toBe("POST");
    expect(lastRequest?.url).toBe("/memory/extract");
    expect(JSON.parse(lastRequest?.body ?? "{}")).toEqual({
      tenant_id: "tenant-a",
      session_id: "s1",
      run_id: "run-1",
      user_message: "hi",
      assistant_reply: "hello",
    });
  });

  it("throws when the service returns a non-2xx status", async () => {
    responseOverride = { status: 500 };
    await expect(
      extractMemory({ tenantId: "t", sessionId: "s", runId: "r", userMessage: "hi", assistantReply: "hello" }),
    ).rejects.toThrow("HTTP 500");
  });
});

describe("consolidateTenant", () => {
  it("POSTs the tenant id to /memory/consolidate", async () => {
    await consolidateTenant("tenant-b");
    expect(lastRequest?.method).toBe("POST");
    expect(lastRequest?.url).toBe("/memory/consolidate");
    expect(JSON.parse(lastRequest?.body ?? "{}")).toEqual({ tenant_id: "tenant-b" });
  });
});

describe("listTenantsWithPendingMemories", () => {
  it("returns [] without calling the service when given an empty list", async () => {
    const result = await listTenantsWithPendingMemories([]);
    expect(result).toEqual([]);
    expect(lastRequest).toBeUndefined();
  });

  it("GETs /memory/tenants-with-pending with a comma-joined query param", async () => {
    responseOverride = { status: 200, body: { tenant_ids: ["tenant-a"] } };
    const result = await listTenantsWithPendingMemories(["tenant-a", "tenant-b"]);
    expect(lastRequest?.url).toBe("/memory/tenants-with-pending?tenant_ids=tenant-a%2Ctenant-b");
    expect(result).toEqual(["tenant-a"]);
  });
});

describe("listMemorySummary", () => {
  it("GETs /memory/summary with tenant_id and returns entries", async () => {
    responseOverride = { status: 200, body: { entries: [{ type: "profile", title: "职业" }] } };
    const result = await listMemorySummary("tenant-a");
    expect(lastRequest?.url).toBe("/memory/summary?tenant_id=tenant-a");
    expect(result).toEqual([{ type: "profile", title: "职业" }]);
  });
});

describe("HttpMemoryStore", () => {
  it("search() POSTs to /memory/search and returns results", async () => {
    responseOverride = { status: 200, body: { results: [{ key: "职业", value: "工程师" }] } };
    const store = new HttpMemoryStore();
    const results = await store.search("职业", { tenantId: "tenant-a", sessionId: "s1" });
    expect(lastRequest?.url).toBe("/memory/search");
    expect(JSON.parse(lastRequest?.body ?? "{}")).toEqual({ tenant_id: "tenant-a", query: "职业" });
    expect(results).toEqual([{ key: "职业", value: "工程师" }]);
  });

  it("read()/write() reject — no memory-service endpoint backs them", async () => {
    const store = new HttpMemoryStore();
    await expect(store.read("k", { tenantId: "t", sessionId: "s" })).rejects.toThrow("not implemented");
    await expect(store.write("k", "v", { tenantId: "t", sessionId: "s" })).rejects.toThrow("not implemented");
  });
});
