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

// 命令调用整段（python3 scripts/main.py / bash foo.sh ...）→ 自然语言。
const COMMAND_CALL = /\b(?:python3?|node|bash|sh|zsh|npm|pnpm|uv)\s+[\w./~-]+/gi;
// 残余的脚本/文件路径（scripts/main.py 等）。
const SCRIPT_PATH = /[\w./~-]+\.(?:py|js|mjs|cjs|sh|ts|tsx)\b/gi;
// 工具/函数名 → 自然语言（口径与 humanizeToolCall 一致）；finish 直接删（避免“然后 finish 给出…”这类冗余）。
const CODE_TERMS: [RegExp, string][] = [
  [/\brun_skill_script\b/gi, "运行技能脚本"],
  [/\bread_skill\b/gi, "读取技能"],
  [/\bweb_search\b/gi, "网页搜索"],
  [/\bweb_extractor\b/gi, "抓取网页"],
  [/\bdispatch_subagent\b/gi, "派发子任务"],
  [/\bask_peer_agent\b/gi, "询问协作 Agent"],
  [/\bfinish\b/gi, ""],
  [/\bbash\b/gi, "命令行"],
  [/\bpython3?\b/gi, "脚本"],
  [/\bskills?\b/gi, "技能"],
];

// 去掉思维链里的代码级信息：命令调用、脚本路径、工具/函数名，换成自然语言。
function stripCodeInfo(text: string): string {
  let out = text.replace(COMMAND_CALL, "运行命令").replace(SCRIPT_PATH, "脚本");
  for (const [pattern, replacement] of CODE_TERMS) out = out.replace(pattern, replacement);
  // 删除 finish 等后可能留下多余空格，压平。
  return out.replace(/[ \t]{2,}/g, " ");
}

export function humanizeReasoning(raw: string): string {
  if (!raw) return "";
  const text = stripCodeInfo(
    raw
      .replace(CLOSED_FENCE, "")
      .replace(OPEN_FENCE, "")
      .replace(INLINE_CODE, "$1")
      .replace(HEADING_PREFIX, "")
      .replace(UNORDERED_BULLET, "• "),
  )
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
  read: "读取文件",
  bash: "执行命令",
  ask_peer_agent: "询问协作 Agent",
  dispatch_subagent: "派发子任务",
  finish: "整理答案",
};

// 从参数里挑一个最适合做人类可读摘要的字段；顺序即优先级（短描述优先于长 prompt）。
const DETAIL_KEYS = [
  "query",
  "question",
  "command",
  "description",
  "prompt",
  "urls",
  "url",
  "path",
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
