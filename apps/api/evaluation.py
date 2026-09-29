"""Agent 评估：绑定 ChatRuntime/ModelClient 的应用层逻辑，定位同 suggest.py——不进
packages/*（那里是通用 agent 框架库，"跑一次真实对话再让 LLM 打分"是这个 Web 应用自己的关注点）。
"""
import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from core.model import ModelClient
from pydantic import BaseModel

if TYPE_CHECKING:
    from runtime import ChatRuntime

_ENCODING = "utf-8"


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


async def judge_reply(
    client: ModelClient,
    instruction: str,
    expected_answer: str | None,
    reply: str,
    *,
    timeout: float = _JUDGE_TIMEOUT_S,
) -> EvalScore | None:
    """LLM 裁判打分——和 suggest.py 一样的哲学：失败不抛异常，返回 None 让调用方展示"评分失败"。"""
    prompt = f"任务指令：{instruction}\n"
    if expected_answer:
        prompt += f"参考答案：{expected_answer}\n"
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
            correctness=int(data["correctness"]),
            completeness=int(data["completeness"]),
            clarity=int(data["clarity"]),
            comment=str(data.get("comment", "")),
        )
    except Exception:  # noqa: BLE001 - 裁判失败不影响其他用例，调用方看到 None 展示"评分失败"
        return None
