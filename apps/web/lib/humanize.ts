// 工具调用 → 自然语言（供"思考过程"面板展示 agent 正在做什么）。这里刻意不包含命令、参数、
// 文件路径等系统内部信息——那些会泄露实现细节。未登记的工具（如 MCP 动态注册的）回退成原始名字。

const TOOL_LABELS: Record<string, string> = {
  bash: "运行技能脚本",
  read: "读取技能文档",
  read_skill: "读取技能文档",
  run_skill_script: "运行技能脚本",
  web_search: "网页搜索",
  web_extractor: "抓取网页",
  dispatch_subagent: "派发子任务",
  ask_peer_agent: "询问协作 Agent",
  finish: "整理答案",
};

// "思考过程"面板用的动作名。
export function toolActionLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

// 审批卡片用：动作名 + 一句人类可读的参数摘要（审批场景需要知道具体在批准什么，故保留参数）。
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
