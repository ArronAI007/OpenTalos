import { describe, expect, it } from "vitest";
import { sortTasks } from "./task-sort";
import type { Task } from "./api";

const task = (id: string, updatedAt: string, pinned = false): Task => ({
  id,
  title: `任务 ${id}`,
  agent_type: "react",
  updated_at: updatedAt,
  pinned,
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
