// 输入框内 @ 提及的纯逻辑：检测正在输入的 @ 查询、把已输入片段剔除。
// 抽成无 React 依赖的纯函数，便于单测覆盖边界（邮箱误触发、IME、光标位置）。

export interface MentionQuery {
  /** `@` 在字符串中的下标（替换/剔除时的起点） */
  start: number;
  /** `@` 之后、光标之前的已输入过滤串（可为空） */
  query: string;
}

/**
 * 检测光标前是否正处于一次 `@` 提及输入中。
 *
 * 约束（避免误触发）：
 * - `@` 必须位于行首或紧跟空白字符（`foo@bar`、邮箱等不触发）；
 * - `@` 与光标之间不能有空白（输入空格即视为放弃本次提及）。
 *
 * 返回 null 表示当前不展示候选列表。
 */
export function detectMentionQuery(value: string, cursor: number): MentionQuery | null {
  const end = Math.max(0, Math.min(cursor, value.length));
  const before = value.slice(0, end);
  const at = before.lastIndexOf("@");
  if (at === -1) return null;
  if (at > 0 && !/\s/.test(before[at - 1])) return null;
  const query = before.slice(at + 1);
  if (/\s/.test(query)) return null;
  return { start: at, query };
}

export interface StripMentionResult {
  value: string;
  cursor: number;
}

/**
 * 选中某个 Agent 后，把已输入的 `@query` 片段从文本中剔除（不把 Agent 名写进正文——
 * 绑定关系由输入框左侧的标签表达）。start 来自 {@link detectMentionQuery}，
 * cursor 为当前光标，用于只删 `@query` 而不误删光标之后的文本。
 */
export function stripMention(value: string, cursor: number, start: number): StripMentionResult {
  const end = Math.max(start, Math.min(cursor, value.length));
  return { value: value.slice(0, start) + value.slice(end), cursor: start };
}
