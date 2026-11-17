import { describe, expect, test, vi } from "vitest";

import {
  localSessionsUrl,
  resumeCommand,
} from "./local-sessions-api";

vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8400/");

describe("local sessions API", () => {
  test("builds source and query filters", () => {
    expect(localSessionsUrl("claude-code", " Open Talos ")).toBe(
      "http://localhost:8400/api/local-sessions?source=claude-code&q=Open+Talos"
    );
  });

  test("returns known resume commands", () => {
    expect(resumeCommand("codex", "abc")).toBe("codex resume abc");
    expect(resumeCommand("claude-code", "def")).toBe(
      "claude --resume def"
    );
    expect(resumeCommand("pi", "pi-id")).toBe("pi --session pi-id");
    expect(resumeCommand("unknown", "ghi")).toBe("");
  });
});
