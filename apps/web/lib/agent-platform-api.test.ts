import { describe, expect, test } from "vitest";

import { agentCatalogUrl } from "./agent-platform-api";

describe("agentCatalogUrl", () => {
  test("encodes installed and search filters", () => {
    expect(
      agentCatalogUrl("http://localhost:8400/", {
        installedOnly: true,
        query: "Claude Code",
      })
    ).toBe(
      "http://localhost:8400/api/agent-platform/catalog?installed_only=true&q=Claude+Code"
    );
  });
});
