import { describe, expect, it } from "vitest";
import { formatDateTimeCN, formatHM } from "./format-time";

// 用显式本地字段构造 Date，断言与时区无关
describe("formatHM", () => {
  it("formats double-digit hour and minute as-is", () => {
    expect(formatHM(new Date(2026, 8, 22, 11, 16).getTime())).toBe("11:16");
  });

  it("zero-pads single-digit hour and minute", () => {
    expect(formatHM(new Date(2026, 0, 5, 9, 5).getTime())).toBe("09:05");
  });
});

describe("formatDateTimeCN", () => {
  it("formats as YYYY年M月D日 HH:MM (month/day not zero-padded)", () => {
    expect(formatDateTimeCN(new Date(2026, 8, 22, 11, 16).getTime())).toBe("2026年9月22日 11:16");
    expect(formatDateTimeCN(new Date(2026, 0, 5, 9, 5).getTime())).toBe("2026年1月5日 09:05");
  });
});
