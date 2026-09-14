import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { MAX_INPUT_TEXT_BYTES, runSandboxedScript } from "./run-sandboxed-script.js";

const FIXTURES_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "fixtures");

describe("runSandboxedScript", () => {
  it("rejects oversized inputText immediately, without starting a container", async () => {
    const oversizedInput = "a".repeat(MAX_INPUT_TEXT_BYTES + 1);
    const start = Date.now();

    await expect(
      runSandboxedScript({
        scriptHostPath: resolve(FIXTURES_DIR, "echo.js"),
        args: [],
        inputText: oversizedInput,
      }),
    ).rejects.toThrow(/input.*too large|exceeds.*limit/i);

    // A real container start/exec cycle takes multiple seconds; this validation must fail fast,
    // well under that, to prove it never touches Docker.
    expect(Date.now() - start).toBeLessThan(1_000);
  });

  it("accepts inputText right at the limit (boundary check)", async () => {
    const exactlyAtLimit = "a".repeat(MAX_INPUT_TEXT_BYTES);
    await expect(
      runSandboxedScript({
        scriptHostPath: resolve(FIXTURES_DIR, "echo.js"),
        args: [],
        inputText: exactlyAtLimit,
      }),
    ).resolves.toMatchObject({ exitCode: 0 });
  }, 30_000);

  it(
    "runs a script and captures its stdout, given args and input text",
    async () => {
      const result = await runSandboxedScript({
        scriptHostPath: resolve(FIXTURES_DIR, "echo.js"),
        args: ["hello", "world"],
        inputText: "some input text",
      });
      expect(result.exitCode).toBe(0);
      expect(result.timedOut).toBe(false);
      expect(JSON.parse(result.stdout.trim())).toEqual({
        args: ["hello", "world"],
        inputText: "some input text",
      });
    },
    30_000,
  );

  it(
    "runs with no network access",
    async () => {
      const result = await runSandboxedScript({
        scriptHostPath: resolve(FIXTURES_DIR, "network-check.js"),
        args: [],
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout.trim()).toMatch(/^BLOCKED:/);
    },
    30_000,
  );

  it(
    "kills the container and reports timedOut when the script runs past the deadline",
    async () => {
      const result = await runSandboxedScript({
        scriptHostPath: resolve(FIXTURES_DIR, "infinite-loop.js"),
        args: [],
        timeoutMs: 2_000,
      });
      expect(result.timedOut).toBe(true);
    },
    30_000,
  );
});
