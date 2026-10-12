import { describe, expect, test } from "vitest";
import { formatDuration, statusLabel } from "./page";

describe("statusLabel", () => {
  test("renders a checkmark for completed runs", () => {
    expect(statusLabel("completed")).toBe("✓");
  });

  test("renders an x for failed runs", () => {
    expect(statusLabel("failed")).toBe("✗");
  });

  test("renders Chinese text for running runs", () => {
    expect(statusLabel("running")).toBe("进行中");
  });

  test("falls back to the raw status for anything else", () => {
    expect(statusLabel("weird")).toBe("weird");
  });
});

describe("formatDuration", () => {
  test("shows 进行中 for a still-running run regardless of duration_seconds", () => {
    expect(formatDuration({ status: "running", duration_seconds: 0 })).toBe("进行中");
  });

  test("formats completed runs with one decimal and a trailing s", () => {
    expect(formatDuration({ status: "completed", duration_seconds: 12.34 })).toBe("12.3s");
  });

  test("formats failed runs the same way as completed", () => {
    expect(formatDuration({ status: "failed", duration_seconds: 3 })).toBe("3.0s");
  });
});
