import { describe, expect, test, vi } from "vitest";

describe("gateway api", () => {
  test("builds normalized gateway endpoint", async () => {
    vi.stubEnv("NEXT_PUBLIC_GATEWAY_URL", "http://127.0.0.1:3425/");
    vi.resetModules();
    const api = await import("./gateway-api");
    expect(api.gatewayEndpoint("/v1/models")).toBe(
      "http://127.0.0.1:3425/v1/models"
    );
    vi.unstubAllEnvs();
  });
});
