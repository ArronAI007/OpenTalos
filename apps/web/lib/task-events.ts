// 跨组件的轻量通知：任务页的 SSE 流收到新标题时，侧栏任务列表（独立组件、独立 state）
// 需要同步更新，但两者之间没有共享的状态管理方案——用浏览器原生 CustomEvent 解耦，
// 不为这一个场景引入全局状态库。
export const TASK_TITLE_UPDATED_EVENT = "opentalos:task-title-updated";

export interface TaskTitleUpdatedDetail {
  taskId: string;
  title: string;
}

export function emitTaskTitleUpdated(taskId: string, title: string): void {
  window.dispatchEvent(
    new CustomEvent<TaskTitleUpdatedDetail>(TASK_TITLE_UPDATED_EVENT, { detail: { taskId, title } })
  );
}
