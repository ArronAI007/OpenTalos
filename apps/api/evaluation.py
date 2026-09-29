"""Agent 评估：绑定 ChatRuntime/ModelClient 的应用层逻辑，定位同 suggest.py——不进
packages/*（那里是通用 agent 框架库，"跑一次真实对话再让 LLM 打分"是这个 Web 应用自己的关注点）。
"""
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
