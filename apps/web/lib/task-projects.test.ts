import { describe, expect, it } from "vitest";
import { partitionTasks, visibleUngrouped } from "./task-projects";
import type { Project, Task } from "./api";

// 归档任务不进主列表（服务端已过滤、调用方也不传），工厂固定 archived: false。
const task = (
  id: string,
  updatedAt: string,
  projectId: string | null = null,
  opts?: { pinned?: boolean; starred?: boolean },
): Task => ({
  id,
  title: `任务 ${id}`,
  agent_type: "react",
  updated_at: updatedAt,
  pinned: opts?.pinned ?? false,
  starred: opts?.starred ?? false,
  archived: false,
  project_id: projectId,
});

describe("partitionTasks", () => {
  it("空输入返回空分组", () => {
    const { ungrouped, byProject } = partitionTasks([]);
    expect(ungrouped).toEqual([]);
    expect(byProject.size).toBe(0);
  });

  it("纯未归组任务全部进 ungrouped，且沿用三级排序", () => {
    const { ungrouped, byProject } = partitionTasks([
      task("a", "2026-01-15T10:00:00"),
      task("b", "2026-01-10T08:00:00", null, { pinned: true }), // 更旧但已固定
    ]);
    expect(ungrouped.map((t) => t.id)).toEqual(["b", "a"]);
    expect(byProject.size).toBe(0);
  });

  it("多项目混合：按 project_id 分到各自组", () => {
    const { ungrouped, byProject } = partitionTasks([
      task("a", "2026-01-15T10:00:00", "p1"),
      task("b", "2026-01-14T09:00:00"),
      task("c", "2026-01-13T08:00:00", "p2"),
      task("d", "2026-01-12T07:00:00", "p1"),
    ]);
    expect(ungrouped.map((t) => t.id)).toEqual(["b"]);
    expect(byProject.get("p1")?.map((t) => t.id)).toEqual(["a", "d"]);
    expect(byProject.get("p2")?.map((t) => t.id)).toEqual(["c"]);
  });

  it("组内各自三级排序（固定 > 收藏 > 普通），不跨组生效", () => {
    const { byProject } = partitionTasks([
      task("plain", "2026-01-15T10:00:00", "p1"),
      task("starred", "2026-01-10T08:00:00", "p1", { starred: true }), // 最旧但已收藏
      task("pinned", "2026-01-12T08:00:00", "p1", { pinned: true }),
      task("other", "2026-01-11T08:00:00", "p2"),
    ]);
    expect(byProject.get("p1")?.map((t) => t.id)).toEqual(["pinned", "starred", "plain"]);
    expect(byProject.get("p2")?.map((t) => t.id)).toEqual(["other"]);
  });

  it("不修改入参（不可变）", () => {
    const input = [task("a", "2026-01-15T10:00:00", "p1"), task("b", "2026-01-10T08:00:00")];
    const snapshot = input.map((t) => ({ ...t }));
    partitionTasks(input);
    expect(input).toEqual(snapshot); // 入参原序不变
  });
});

const project = (id: string): Project => ({ id, name: `项目 ${id}`, created_at: "2026-01-01T00:00:00" });

describe("visibleUngrouped", () => {
  it("projects 拉取失败（空列表）时，所有分组任务并入未归组可见", () => {
    const { ungrouped, byProject } = partitionTasks([
      task("a", "2026-01-15T10:00:00", "p1"),
      task("b", "2026-01-14T09:00:00"),
      task("c", "2026-01-13T08:00:00", "p2"),
    ]);
    // 无项目元数据 → 不存在"孤儿"之外的归属，全部按三级排序并列展示
    expect(visibleUngrouped(ungrouped, byProject, []).map((t) => t.id)).toEqual(["a", "b", "c"]);
  });

  it("未知 project_id 的桶并入未归组；已匹配项目的桶保持独立不双计", () => {
    const { ungrouped, byProject } = partitionTasks([
      task("known", "2026-01-15T10:00:00", "p1"),
      task("ghost", "2026-01-14T09:00:00", "p-ghost"), // 引用了不存在的项目
      task("plain", "2026-01-13T08:00:00"),
    ]);
    const visible = visibleUngrouped(ungrouped, byProject, [project("p1")]);
    expect(visible.map((t) => t.id)).toEqual(["ghost", "plain"]); // 孤儿并入且重排
    expect(byProject.get("p1")?.map((t) => t.id)).toEqual(["known"]); // 已匹配桶不受影响
    expect(visible.some((t) => t.id === "known")).toBe(false); // 不重复出现
  });

  it("无孤儿桶时原样返回同一引用（防无谓重渲染/分配）", () => {
    const { ungrouped, byProject } = partitionTasks([
      task("a", "2026-01-15T10:00:00", "p1"),
      task("b", "2026-01-14T09:00:00"),
    ]);
    expect(visibleUngrouped(ungrouped, byProject, [project("p1")])).toBe(ungrouped);
  });
});
