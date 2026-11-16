import { describe, expect, test, vi } from "vitest";

describe("m7 api", () => {
  test("builds normalized M7 endpoints", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8400/");
    vi.resetModules();
    const api = await import("./m7-api");
    expect(api.m7Endpoint("/privacy/rules")).toBe(
      "http://localhost:8400/api/m7/privacy/rules"
    );
    vi.unstubAllEnvs();
  });
});
