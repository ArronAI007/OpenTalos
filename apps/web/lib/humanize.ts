// 把模型输出整理成自然语言的"思考过程"展示（对齐 Codex / 豆包）：
// - humanizeReasoning：原始思维链（reasoning_content）去掉代码围栏/行内代码等"代码感"内容，
//   压平空白，让它读起来像一段自然语言叙述；
// - humanizeToolCall：把工具调用从 `tool({"k":"v"})` 翻译成自然语言动作 + 一句人类可读的摘要。

const CLOSED_FENCE = /```[\s\S]*?```/g;
// 流式中围栏可能还没闭合：从最后一个未闭合的 ``` 起全部当作代码去掉。
const OPEN_FENCE = /```[\s\S]*$/;
const INLINE_CODE = /`([^`\n]+)`/g;
const HEADING_PREFIX = /^[ \t]{0,3}#{1,6}[ \t]+/gm;
const UNORDERED_BULLET = /^[ \t]*[-*+][ \t]+/gm;

export function humanizeReasoning(raw: string): string {
  if (!raw) return "";
  const text = raw
    .replace(CLOSED_FENCE, "")
    .replace(OPEN_FENCE, "")
    .replace(INLINE_CODE, "$1")
    .replace(HEADING_PREFIX, "")
    .replace(UNORDERED_BULLET, "• ")
    .split("\n")
    .map((line) => line.replace(/[ \t]+$/, ""))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return text;
}

// 已知工具 -> 自然语言动词。未登记的工具（如 MCP 动态注册的）回退成原始名字。
const TOOL_LABELS: Record<string, string> = {
  web_search: "网页搜索",
  web_extractor: "抓取网页",
  read_skill: "读取技能",
  run_skill_script: "运行脚本",
  ask_peer_agent: "询问协作 Agent",
  dispatch_subagent: "派发子任务",
  finish: "整理答案",
};

// 从参数里挑一个最适合做人类可读摘要的字段；顺序即优先级（短描述优先于长 prompt）。
const DETAIL_KEYS = [
  "query",
  "question",
  "skill_name",
  "description",
  "prompt",
  "urls",
  "url",
  "path",
  "input_text",
  "text",
  "name",
];

const DETAIL_MAX = 60;

export function humanizeToolCall(
  name: string,
  args: Record<string, unknown> | undefined,
): { label: string; detail: string } {
  const label = TOOL_LABELS[name] ?? name;
  let detail = "";
  for (const key of DETAIL_KEYS) {
    const value = args?.[key];
    if (value === undefined || value === null || value === "") continue;
    detail = Array.isArray(value) ? value.map(String).join(", ") : String(value);
    break;
  }
  detail = detail.replace(/\s+/g, " ").trim();
  if (detail.length > DETAIL_MAX) detail = `${detail.slice(0, DETAIL_MAX)}…`;
  return { label, detail };
}
