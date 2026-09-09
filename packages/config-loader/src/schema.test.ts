import { describe, expect, it } from "vitest";
import { loadGraphConfig } from "./schema.js";

describe("loadGraphConfig", () => {
  it("parses a YAML graph config into a validated GraphConfig", () => {
    const yaml = `
id: greeting-agent
entryNode: greet
nodes:
  greet:
    use: greetNode
edges:
  - from: greet
    to: greet
    when: shouldRepeat
`;
    const config = loadGraphConfig(yaml);
    expect(config).toEqual({
      id: "greeting-agent",
      entryNode: "greet",
      nodes: { greet: { use: "greetNode" } },
      edges: [{ from: "greet", to: "greet", when: "shouldRepeat" }],
    });
  });

  it("parses a JSON graph config", () => {
    const json = JSON.stringify({
      id: "g",
      entryNode: "n1",
      nodes: { n1: { use: "factoryA" } },
      edges: [],
    });
    const config = loadGraphConfig(json);
    expect(config.id).toBe("g");
  });

  it("rejects a config missing a required field", () => {
    expect(() => loadGraphConfig(JSON.stringify({ id: "g", nodes: {}, edges: [] }))).toThrow();
  });
});
