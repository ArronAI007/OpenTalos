import { describe, expect, it } from "vitest";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { z } from "zod";
import type { TenantContext } from "@opentalos/core-types";
import { createMcpTools } from "./mcp-adapter.js";

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

async function startLinkedServerAndClient(): Promise<Client> {
  const server = new McpServer({ name: "test-server", version: "1.0.0" });
  server.registerTool(
    "echo",
    { description: "Echoes the input text back", inputSchema: { text: z.string() } },
    async ({ text }) => ({ content: [{ type: "text", text }] }),
  );

  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "test-client", version: "1.0.0" });
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  return client;
}

async function startServerWithFailingTool(): Promise<Client> {
  const server = new McpServer({ name: "test-server", version: "1.0.0" });
  server.registerTool(
    "fail",
    { description: "Always reports a tool error", inputSchema: {} },
    async () => ({ content: [{ type: "text", text: "something went wrong" }], isError: true }),
  );

  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "test-client", version: "1.0.0" });
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  return client;
}

describe("createMcpTools", () => {
  it("adapts a real MCP server's tools into OpenTalos Tool objects", async () => {
    const client = await startLinkedServerAndClient();
    const tools = await createMcpTools(client);

    expect(tools).toHaveLength(1);
    expect(tools[0].definition.name).toBe("echo");

    const result = await tools[0].execute({ text: "hello mcp" }, tenant);
    expect(result.isError).toBeFalsy();
    expect(result.output).toBe("hello mcp");
  });

  it("surfaces an MCP tool's isError result through the adapted Tool", async () => {
    const client = await startServerWithFailingTool();
    const tools = await createMcpTools(client);

    expect(tools).toHaveLength(1);
    expect(tools[0].definition.name).toBe("fail");

    const result = await tools[0].execute({}, tenant);
    expect(result.isError).toBe(true);
    expect(result.output).toBe("something went wrong");
  });
});
