import { describe, expect, it } from "vitest";
import type { TenantContext, Tool } from "@opentalos/core-types";
import { InMemoryToolRegistry } from "./in-memory-registry.js";

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

const echoTool: Tool = {
  definition: { name: "echo", description: "Echoes the input text", inputSchema: { type: "object" } },
  async execute(input) {
    return { id: "call-1", output: input };
  },
};

const throwingTool: Tool = {
  definition: { name: "boom", description: "Always throws", inputSchema: { type: "object" } },
  async execute() {
    throw new Error("kaboom");
  },
};

const mismatchedIdTool: Tool = {
  definition: { name: "mismatched", description: "Returns a hardcoded id", inputSchema: { type: "object" } },
  async execute() {
    return { id: "tool-invented-id", output: "done" };
  },
};

describe("InMemoryToolRegistry", () => {
  it("registers and lists tool definitions", () => {
    const registry = new InMemoryToolRegistry();
    registry.register(echoTool);
    expect(registry.list()).toEqual([echoTool.definition]);
    expect(registry.get("echo")).toBe(echoTool);
  });

  it("executes a registered tool and returns its result", async () => {
    const registry = new InMemoryToolRegistry();
    registry.register(echoTool);
    const result = await registry.execute({ id: "call-1", name: "echo", input: { text: "hi" } }, tenant);
    expect(result).toEqual({ id: "call-1", output: { text: "hi" } });
  });

  it("returns an error result for an unknown tool name", async () => {
    const registry = new InMemoryToolRegistry();
    const result = await registry.execute({ id: "call-1", name: "missing", input: {} }, tenant);
    expect(result.isError).toBe(true);
  });

  it("catches a thrown error inside a tool and returns it as an error result", async () => {
    const registry = new InMemoryToolRegistry();
    registry.register(throwingTool);
    const result = await registry.execute({ id: "call-1", name: "boom", input: {} }, tenant);
    expect(result.isError).toBe(true);
    expect(result.output).toContain("kaboom");
  });

  it("overrides the tool's own id with the caller's call.id", async () => {
    const registry = new InMemoryToolRegistry();
    registry.register(mismatchedIdTool);
    const result = await registry.execute({ id: "caller-id", name: "mismatched", input: {} }, tenant);
    expect(result.id).toBe("caller-id");
    expect(result.output).toBe("done");
  });
});
