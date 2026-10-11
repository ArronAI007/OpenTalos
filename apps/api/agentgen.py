"""一句话生成 Agent：把用户的一句需求交给模型，产出 Agent 定义（名称/简介/角色设定/技能）。

和 suggest.py 不同，这是用户主动发起的操作——失败必须如实报错（AgentGenerationError），
不能静默成空，否则用户会得到一个"生成成功"的空壳 Agent。
"""
import asyncio
import json
from dataclasses import dataclass

from core.model import ModelClient

_TIMEOUT_S = 60.0
_NAME_MAX = 20
_DESC_MAX = 80
_PROMPT_MAX = 4000
_PROMPT_INPUT_MAX = 500

_SYSTEM = (
    "你是 Agent 设计师。用户会用一句话描述想要的 Agent，你来把它设计成一个可直接使用的定义。"
    "只输出一个 JSON 对象，不要输出任何其他内容，字段如下：\n"
    f'- "name": Agent 的名字，不超过 {_NAME_MAX} 个字；\n'
    f'- "description": 一句话简介，不超过 {_DESC_MAX} 个字；\n'
    '- "system_prompt": 角色设定，用第二人称（"你是…"）写清职责、工作方式、输出风格和边界，'
    "使用与用户需求相同的语言；不要提及工具调用协议或 finish，那些由系统另行提供；\n"
    '- "skills": 从下方「可用技能」中挑选这个 Agent 真正需要的技能名数组，没有合适的就给空数组，'
    "不得编造不在列表中的技能名。"
)


class AgentGenerationError(Exception):
    """模型调用失败，或输出无法解析成合法的 Agent 定义。"""


@dataclass
class AgentSpec:
    name: str
    description: str
    system_prompt: str
    skills: list[str]


def _parse_spec(text: str, available_skills: set[str]) -> AgentSpec:
    """宽松解析：整串 JSON → 截取首个 {...} 片段。缺 name/system_prompt 视为失败；
    技能名按可用清单过滤（模型编造的直接丢弃，不报错）。"""
    candidates = [text.strip()]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    data = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            data = parsed
            break
    if data is None:
        raise AgentGenerationError("模型没有返回有效的 JSON")

    def _text(key: str) -> str:
        value = data.get(key)
        return value.strip() if isinstance(value, str) else ""

    name, system_prompt = _text("name"), _text("system_prompt")
    if not name or not system_prompt:
        raise AgentGenerationError("模型返回的 Agent 缺少名称或角色设定")
    raw_skills = data.get("skills")
    skills: list[str] = []
    if isinstance(raw_skills, list):
        for item in raw_skills:
            if isinstance(item, str) and item in available_skills and item not in skills:
                skills.append(item)
    return AgentSpec(
        name=name[:_NAME_MAX],
        description=_text("description")[:_DESC_MAX],
        system_prompt=system_prompt[:_PROMPT_MAX],
        skills=skills,
    )


async def generate_agent_spec(
    client: ModelClient,
    prompt: str,
    available_skills: list[tuple[str, str]],
    *,
    timeout: float = _TIMEOUT_S,
) -> AgentSpec:
    """available_skills = [(name, description)]：用户「我的技能」里当前可用的技能。"""
    prompt = prompt.strip()[:_PROMPT_INPUT_MAX]
    skills_block = "\n".join(f"- {name}: {desc}" for name, desc in available_skills) or "（无）"
    try:
        completion = await asyncio.wait_for(
            client.acomplete([
                {"role": "system", "content": f"{_SYSTEM}\n\n可用技能：\n{skills_block}"},
                {"role": "user", "content": prompt},
            ]),
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - 统一包成 AgentGenerationError，由端点转成 502
        raise AgentGenerationError(f"模型调用失败：{exc or type(exc).__name__}") from exc
    return _parse_spec(completion.text, {name for name, _ in available_skills})
