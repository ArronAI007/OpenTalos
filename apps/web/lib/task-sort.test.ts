import { describe, expect, it } from "vitest";
import { sortTasks } from "./task-sort";
import type { Task } from "./api";

// 归档任务不进主列表（服务端已过滤），sortTasks 无需感知 archived——故工厂固定 archived: false。
// project_id 同理：排序不感知归组（partitionTasks 负责分组、组内才调用 sortTasks），固定 null。
const task = (id: string, updatedAt: string, pinned = false, starred = false): Task => ({
  id,
  title: `任务 ${id}`,
  agent_type: "react",
  updated_at: updatedAt,
  pinned,
  starred,
  archived: false,
  project_id: null,
});

describe("sortTasks", () => {
  it("固定任务排在最前", () => {
    const tasks = sortTasks([
      task("a", "2026-01-15T10:00:00"),
      task("b", "2026-01-10T08:00:00", true), // 更旧但已固定
      task("c", "2026-01-14T09:00:00"),
    ]);
    expect(tasks.map((t) => t.id)).toEqual(["b", "a", "c"]);
  });

  it("固定组内与普通组内均按 updated_at 降序", () => {
    const tasks = sortTasks([
      task("p1", "2026-01-10T08:00:00", true),
      task("n1", "2026-01-12T08:00:00"),
      task("p2", "2026-01-14T08:00:00", true),
      task("n2", "2026-01-11T08:00:00"),
    ]);
    expect(tasks.map((t) => t.id)).toEqual(["p2", "p1", "n1", "n2"]);
  });

  it("三级次序：固定 > 收藏 > 普通（收藏组 updated_at 更旧仍排普通前）", () => {
    const tasks = sortTasks([
      task("plain", "2026-01-15T10:00:00"),
      task("starred", "2026-01-10T08:00:00", false, true), // 最旧但已收藏
      task("pinned", "2026-01-12T08:00:00", true),
    ]);
    expect(tasks.map((t) => t.id)).toEqual(["pinned", "starred", "plain"]);
  });

  it("收藏组内按 updated_at 降序", () => {
    const tasks = sortTasks([
      task("s1", "2026-01-10T08:00:00", false, true),
      task("n1", "2026-01-13T08:00:00"),
      task("s2", "2026-01-14T08:00:00", false, true),
    ]);
    expect(tasks.map((t) => t.id)).toEqual(["s2", "s1", "n1"]);
  });

  it("不修改入参数组（不可变）", () => {
    const input = [task("a", "2026-01-15T10:00:00"), task("b", "2026-01-10T08:00:00", true)];
    const snapshot = [...input];
    const output = sortTasks(input);
    expect(input).toEqual(snapshot); // 入参原序不变
    expect(output).not.toBe(input); // 返回新数组
  });

  it("空输入返回空数组", () => {
    expect(sortTasks([])).toEqual([]);
  });
});
