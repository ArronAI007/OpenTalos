import { describe, expect, it } from "vitest";
import { filterTasksByTitle } from "./task-filter";
import type { Task } from "./api";

const task = (id: string, title: string): Task => ({ id, title, agent_type: "react", updated_at: "", pinned: false, starred: false });

describe("filterTasksByTitle", () => {
  const tasks = [task("1", "写周报"), task("2", "调研 OpenTalos"), task("3", "Review 代码")];

  it("空 query 原样返回全部", () => {
    expect(filterTasksByTitle(tasks, "")).toBe(tasks);
    expect(filterTasksByTitle(tasks, "   ")).toBe(tasks);
  });

  it("大小写不敏感", () => {
    expect(filterTasksByTitle(tasks, "opentalos").map((t) => t.id)).toEqual(["2"]);
  });

  it("无匹配返回空数组", () => {
    expect(filterTasksByTitle(tasks, "不存在的任务")).toEqual([]);
  });

  it("首尾空格不影响匹配", () => {
    expect(filterTasksByTitle(tasks, "  周报  ").map((t) => t.id)).toEqual(["1"]);
  });

  it("null 标题不抛错且不匹配", () => {
    const mixed: Task[] = [
      task("1", "写周报"),
      { id: "2", title: null as unknown as string, agent_type: "react", updated_at: "", pinned: false, starred: false },
    ];
    expect(filterTasksByTitle(mixed, "周报").map((t) => t.id)).toEqual(["1"]);
  });
});
