import { describe, expect, it } from "vitest";
import { formatTaskTime, groupTasksByDate } from "./task-groups";
import type { Task } from "./api";

const task = (id: string, updatedAt: string): Task => ({
  id,
  title: `任务 ${id}`,
  agent_type: "react",
  updated_at: updatedAt,
  pinned: false,
  starred: false,
  archived: false,
});

// 固定基准时间：2026-01-15 12:00（本地时区）。
const NOW = new Date(2026, 0, 15, 12, 0, 0);

describe("groupTasksByDate", () => {
  it("空输入返回空数组", () => {
    expect(groupTasksByDate([], NOW)).toEqual([]);
  });

  it("按今天/昨天/更早分组，当天 0 点归今天", () => {
    const tasks = [
      task("a", "2026-01-15T00:00:00"), // 今天 0 点
      task("b", "2026-01-14T23:59:59"), // 昨天末尾
      task("c", "2026-01-14T00:00:00"), // 昨天 0 点
      task("d", "2026-01-13T23:59:59"), // 更早末尾
    ];
    const groups = groupTasksByDate(tasks, NOW);
    expect(groups.map((g) => g.key)).toEqual(["today", "yesterday", "earlier"]);
    expect(groups.map((g) => g.label)).toEqual(["今天", "昨天", "更早"]);
    expect(groups[0].tasks.map((t) => t.id)).toEqual(["a"]);
    expect(groups[1].tasks.map((t) => t.id)).toEqual(["b", "c"]);
    expect(groups[2].tasks.map((t) => t.id)).toEqual(["d"]);
  });

  it("只保留非空分组", () => {
    const groups = groupTasksByDate([task("a", "2026-01-10T08:00:00")], NOW);
    expect(groups.map((g) => g.key)).toEqual(["earlier"]);
  });

  it("组内保持传入顺序", () => {
    const tasks = [
      task("a", "2026-01-10T08:00:00"),
      task("b", "2026-01-15T09:00:00"),
      task("c", "2026-01-14T10:00:00"),
      task("d", "2026-01-05T11:00:00"),
      task("e", "2026-01-15T08:00:00"),
    ];
    const groups = groupTasksByDate(tasks, NOW);
    expect(groups[0].tasks.map((t) => t.id)).toEqual(["b", "e"]);
    expect(groups[2].tasks.map((t) => t.id)).toEqual(["a", "d"]);
  });
});

describe("formatTaskTime", () => {
  it("今天格式化为 HH:MM", () => {
    expect(formatTaskTime(new Date(2026, 0, 15, 9, 5), NOW)).toBe("09:05");
    expect(formatTaskTime(new Date(2026, 0, 15, 0, 0), NOW)).toBe("00:00");
  });

  it("昨天格式化为 昨天 HH:MM", () => {
    expect(formatTaskTime(new Date(2026, 0, 14, 23, 30), NOW)).toBe("昨天 23:30");
  });

  it("更早格式化为 YYYY/M/D", () => {
    expect(formatTaskTime(new Date(2025, 11, 31, 8, 0), NOW)).toBe("2025/12/31");
  });
});
