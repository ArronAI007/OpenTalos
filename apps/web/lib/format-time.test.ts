import { describe, expect, it } from "vitest";
import { formatDateTimeCN, formatHM, formatRelativeDay } from "./format-time";

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

// now 可注入保证确定性；构造用显式本地字段，断言与时区无关
describe("formatRelativeDay", () => {
  const now = new Date(2026, 8, 24, 15, 30);

  it("same day shows 今天 HH:MM", () => {
    expect(formatRelativeDay(new Date(2026, 8, 24, 11, 23).getTime(), now)).toBe("今天 11:23");
    expect(formatRelativeDay(new Date(2026, 8, 24, 0, 5).getTime(), now)).toBe("今天 00:05");
  });

  it("previous day shows 昨天 HH:MM (incl. cross-month)", () => {
    expect(formatRelativeDay(new Date(2026, 8, 23, 9, 5).getTime(), now)).toBe("昨天 09:05");
    // 跨月：now=9月1日时 8月31日仍是昨天
    expect(formatRelativeDay(new Date(2026, 7, 31, 22, 0).getTime(), new Date(2026, 8, 1, 6, 0))).toBe("昨天 22:00");
  });

  it("earlier in same year shows M月D日 HH:MM", () => {
    expect(formatRelativeDay(new Date(2026, 5, 3, 8, 7).getTime(), now)).toBe("6月3日 08:07");
  });

  it("earlier year shows YYYY年M月D日 HH:MM", () => {
    expect(formatRelativeDay(new Date(2025, 11, 31, 23, 59).getTime(), now)).toBe("2025年12月31日 23:59");
  });
});
