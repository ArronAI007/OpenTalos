// 聊天流式输出的跟随滚动（stick-to-bottom）纯逻辑：
// 用户位于底部附近时新内容（流式 delta / 新消息）自动顶到底；上翻阅读历史时不抢夺滚动位置。
// 结构类型入参（不依赖 DOM 类型），可用普通对象在 vitest 中直接测。
export const NEAR_BOTTOM_PX = 80;

interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

export function isNearBottom(el: ScrollMetrics, threshold: number = NEAR_BOTTOM_PX): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

export function scrollToBottom(el: ScrollMetrics): void {
  el.scrollTop = el.scrollHeight;
}
