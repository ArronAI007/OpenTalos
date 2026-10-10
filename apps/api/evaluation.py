"""Agent 评估：绑定 ChatRuntime/ModelClient 的应用层逻辑，定位同 suggest.py——不进
packages/*（那里是通用 agent 框架库，"跑一次真实对话再让 LLM 打分"是这个 Web 应用自己的关注点）。
"""
import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from core.cancellation import CancellationToken
from core.model import ModelClient
from pydantic import BaseModel

if TYPE_CHECKING:
    from runtime import ChatRuntime

_ENCODING = "utf-8"

# 评估对比的 agent 类型。当前只有单一 ReActAgent（历史遗留的 4 个标签跑的是同一个 agent，
# 对比无意义且会 4 倍浪费模型调用），故收敛为一种。
EVAL_AGENT_TYPES = ["react"]


class EvalCase(BaseModel):
    id: str
    name: str
    instruction: str
    expected_answer: str | None = None


class EvalScore(BaseModel):
    correctness: int
    completeness: int
    clarity: int
    comment: str


class EvalResult(BaseModel):
    case_id: str
    case_name: str
    agent_type: str
    reply: str | None
    score: EvalScore | None
    error: str | None
    latency_ms: int
    tokens_used: int
    # 新增：真实成本（有价目时）与工具轨迹，供报告展示与问题定位。
    cost: float | None = None
    tool_calls: int = 0
    tool_failures: int = 0
    tools_used: list[str] = []


def load_eval_cases(store_path: Path) -> list[EvalCase]:
    if not store_path.is_file():
        return []
    data = json.loads(store_path.read_text(encoding=_ENCODING))
    return [EvalCase.model_validate(item) for item in data]


def save_eval_cases(store_path: Path, cases: list[EvalCase]) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        json.dumps([c.model_dump() for c in cases], ensure_ascii=False), encoding=_ENCODING
    )


def add_eval_case(store_path: Path, name: str, instruction: str, expected_answer: str | None) -> EvalCase:
    cases = load_eval_cases(store_path)
    case = EvalCase(id=uuid4().hex, name=name, instruction=instruction, expected_answer=expected_answer)
    cases.append(case)
    save_eval_cases(store_path, cases)
    return case


def remove_eval_case(store_path: Path, case_id: str) -> None:
    """幂等：case_id 本来就不存在也不报错。"""
    cases = [c for c in load_eval_cases(store_path) if c.id != case_id]
    save_eval_cases(store_path, cases)


_JUDGE_TIMEOUT_S = 30.0
_JUDGE_SYSTEM = (
    "你是一个严格的 AI 助手能力评估员。根据任务指令（和可选的参考答案），给这段回复在以下三个"
    "维度打 1-5 的整数分：正确性（correctness，是否准确无误，有参考答案时以其为准）、"
    "完整性（completeness，是否完整回应了任务指令的所有要求）、"
    "清晰度（clarity，表达是否清楚易懂、结构合理）。"
    '只返回 JSON：{"correctness": int, "completeness": int, "clarity": int, "comment": "一句话点评"}，'
    "不要输出其他任何内容。"
)


def _extract_json_object(text: str) -> str:
    """从模型输出里宽松提取第一个 {...} JSON 对象文本——模型可能在 JSON 前后加了闲话。
    找不到花括号就原样返回整个文本，交给 json.loads 自己抛错（上层统一 except 兜底）。"""
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _to_score(value: object) -> int:
    """分数规范化：非整数抛错（由 judge_reply 统一兜底为 None），超范围的夹到 1-5。"""
    return max(1, min(5, int(value)))  # type: ignore[arg-type]


async def judge_reply(
    client: ModelClient,
    instruction: str,
    expected_answer: str | None,
    reply: str,
    *,
    tools: list[str] | None = None,
    timeout: float = _JUDGE_TIMEOUT_S,
) -> EvalScore | None:
    """LLM 裁判打分——和 suggest.py 一样的哲学：失败不抛异常，返回 None 让调用方展示"评分失败"。
    带上本轮调用的工具，让裁判在了解 agent 做了什么的前提下打分。"""
    prompt = f"任务指令：{instruction}\n"
    if expected_answer:
        prompt += f"参考答案：{expected_answer}\n"
    if tools:
        prompt += f"本轮 agent 调用的工具：{', '.join(tools)}\n"
    prompt += f"待评估回复：{reply}"
    try:
        completion = await asyncio.wait_for(
            client.acomplete([
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ]),
            timeout=timeout,
        )
        data = json.loads(_extract_json_object(completion.text))
        return EvalScore(
            correctness=_to_score(data["correctness"]),
            completeness=_to_score(data["completeness"]),
            clarity=_to_score(data["clarity"]),
            comment=str(data.get("comment", "")),
        )
    except Exception:  # noqa: BLE001 - 裁判失败不影响其他用例，调用方看到 None 展示"评分失败"
        return None


async def run_case(runtime: "ChatRuntime", agent_type: str, case: EvalCase) -> EvalResult:
    """建一个立即归档的任务，复用 stream_reply 真实跑一轮对话，再让裁判打分。
    单条失败（agent 报错/裁判解析失败/建任务时的意外异常）不影响其他组合——这个函数保证不
    向外抛未捕获异常，外层可以放心用 asyncio.gather（不需要 return_exceptions=True）。"""
    start = time.monotonic()
    cancellation = CancellationToken()
    usage: dict[str, object] = {}
    tools_used: list[str] = []
    tool_calls = 0
    tool_failures = 0
    try:
        task = runtime.store.create_task(agent_type)
        runtime.store.update_task(task["id"], archived=1)
        reply: str | None = None
        error: str | None = None
        async for event in runtime.stream_reply(
            task["id"], case.instruction, skip_suggestions=True, cancellation=cancellation
        ):
            kind = event["type"]
            if kind == "done":
                reply = event["reply"]
                usage = event.get("usage") or {}
            elif kind == "error":
                error = event["message"]
            elif kind == "tool_call":
                tool_calls += 1
                name = event.get("name")
                if name and name not in tools_used:
                    tools_used.append(name)
            elif kind == "tool_result" and event.get("ok") is False:
                tool_failures += 1
        score = (
            await judge_reply(runtime.model_client, case.instruction, case.expected_answer, reply, tools=tools_used)
            if reply
            else None
        )
    except Exception as exc:  # noqa: BLE001 - 这条组合失败不能连累其他组合
        return EvalResult(
            case_id=case.id, case_name=case.name, agent_type=agent_type,
            reply=None, score=None, error=str(exc),
            latency_ms=int((time.monotonic() - start) * 1000),
            tokens_used=_resolve_tokens({}, None, cancellation.tokens_used),
        )
    return EvalResult(
        case_id=case.id, case_name=case.name, agent_type=agent_type,
        reply=reply, score=score, error=error,
        latency_ms=int((time.monotonic() - start) * 1000),
        tokens_used=_resolve_tokens(usage, reply, cancellation.tokens_used),
        cost=usage.get("cost") if isinstance(usage.get("cost"), float) else None,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        tools_used=tools_used,
    )


def _resolve_tokens(usage: dict[str, object], reply: str | None, recorded: int) -> int:
    """真实用量优先：本轮 done 事件的 usage.total_tokens → CancellationToken 累计值 → 按回复字符
    数 / 4 的粗略估计（仅在供应商完全不报 usage 时才会走到这一步）。"""
    total = usage.get("total_tokens")
    if isinstance(total, int) and total > 0:
        return total
    if recorded > 0:
        return recorded
    return len(reply) // 4 if reply else 0
