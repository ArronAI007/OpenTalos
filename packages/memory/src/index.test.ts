import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryMemoryStore } from "./index.js";

const tenantA: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };
const tenantB: TenantContext = { tenantId: "tenant-b", sessionId: "session-1" };

describe("InMemoryMemoryStore", () => {
  it("writes and reads a value scoped to a tenant", async () => {
    const store = new InMemoryMemoryStore();
    await store.write("greeting", "hello", tenantA);
    await expect(store.read("greeting", tenantA)).resolves.toBe("hello");
  });

  it("returns undefined for a key never written", async () => {
    const store = new InMemoryMemoryStore();
    await expect(store.read("missing", tenantA)).resolves.toBeUndefined();
  });

  it("isolates values between tenants sharing the same key and sessionId", async () => {
    const store = new InMemoryMemoryStore();
    await store.write("greeting", "hello from A", tenantA);
    await store.write("greeting", "hello from B", tenantB);
    await expect(store.read("greeting", tenantA)).resolves.toBe("hello from A");
    await expect(store.read("greeting", tenantB)).resolves.toBe("hello from B");
  });

  it("finds records whose value contains the search query, scoped to tenant", async () => {
    const store = new InMemoryMemoryStore();
    await store.write("fact-1", "Paris is the capital of France", tenantA);
    await store.write("fact-2", "Tokyo is the capital of Japan", tenantA);
    await store.write("fact-1", "Berlin is the capital of Germany", tenantB);

    const results = await store.search("capital of france", tenantA);
    expect(results).toEqual([{ key: "fact-1", value: "Paris is the capital of France" }]);
  });
});
