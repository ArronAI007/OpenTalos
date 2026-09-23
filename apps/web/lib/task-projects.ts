import type { Project, Task } from "@/lib/api";
import { sortTasks } from "@/lib/task-sort";

export interface TaskPartitions {
  ungrouped: Task[];
  byProject: Map<string, Task[]>;
}

// 任务按 project_id 分组：未归组列表与各项目组内都沿用全局三级排序（sortTasks），
// 固定/收藏不跨组生效。入参即可见列表（归档过滤由调用方/服务端负责）。返回新结构，不修改入参。
export function partitionTasks(tasks: Task[]): TaskPartitions {
  const ungrouped: Task[] = [];
  const byProject = new Map<string, Task[]>();
  for (const task of tasks) {
    if (task.project_id === null) {
      ungrouped.push(task);
    } else {
      const group = byProject.get(task.project_id);
      if (group) group.push(task);
      else byProject.set(task.project_id, [task]);
    }
  }
  return {
    ungrouped: sortTasks(ungrouped),
    byProject: new Map([...byProject].map(([id, group]) => [id, sortTasks(group)])),
  };
}

// byProject 中找不到对应项目元数据的桶（projects 拉取失败或 project_id 引用漂移），
// 并入未归组展示，避免任务从侧栏静默消失；无孤儿桶时原样返回（不引入多余分配）。
export function visibleUngrouped(ungrouped: Task[], byProject: Map<string, Task[]>, projects: Project[]): Task[] {
  const ids = new Set(projects.map((p) => p.id));
  const orphans = [...byProject.entries()]
    .filter(([projectId]) => !ids.has(projectId))
    .flatMap(([, bucket]) => bucket);
  return orphans.length === 0 ? ungrouped : sortTasks([...ungrouped, ...orphans]);
}
