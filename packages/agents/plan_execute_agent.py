import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from core.agent import Agent, AssemblyConfig, OutputTrimmer, RuntimeSettings
from core.agent_loop import run_tool_turn
from core.protocol import ChatMessage
from core.model import ModelClient
from tool.registry import ToolRegistry

DEFAULT_PLANNER_PROMPT = "You break a complex question into an ordered list of independent, executable sub-steps."
DEFAULT_RUNNER_PROMPT = "You execute a single step of a larger plan, using the prior steps' results as context."

PROPOSE_STEPS_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_steps",
        "description": "Propose an ordered list of steps to solve the question.",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered, independently executable steps.",
                }
            },
            "required": ["steps"],
        },
    },
}


@dataclass
class RoleConfig:
    name: str
    description: str
    peer_url: str


@dataclass
class PlanStep:
    text: str
    role: str | None = None


RoleDispatcher = Callable[[str, str], Awaitable[str]]


def _build_propose_steps_tool(roles: list[RoleConfig]) -> dict:
    if not roles:
        return PROPOSE_STEPS_TOOL
    role_names = [r.name for r in roles]
    role_summary = "; ".join(f"{r.name}: {r.description}" for r in roles)
    return {
        "type": "function",
        "function": {
            "name": "propose_steps",
            "description": "Propose an ordered list of steps to solve the question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "description": "What this step does."},
                                "role": {
                                    "type": "string",
                                    "enum": role_names,
                                    "description": (
                                        f"Optional: assign this step to one of the available roles "
                                        f"({role_summary}). Omit to execute the step yourself."
                                    ),
                                },
                            },
                            "required": ["text"],
                        },
                        "description": "Ordered, independently executable steps.",
                    }
                },
                "required": ["steps"],
            },
        },
    }


def _normalize_step(raw: object) -> PlanStep:
    if isinstance(raw, dict):
        return PlanStep(text=raw.get("text", ""), role=raw.get("role"))
    return PlanStep(text=str(raw))


class PlanExecuteAgent(Agent):
    """先把问题拆成有序步骤（强制 function call），再逐步执行，滚动累积上下文。

    传入非空 `roles` 时，规划阶段的 function-call schema 会让模型可选地给每步分配一个角色
    名；没有角色可用时 schema/prompt 和不带角色概念的原版完全一致。
    """

    def __init__(
        self,
        name: str,
        model_client: ModelClient,
        system_prompt: str | None = None,
        settings: RuntimeSettings | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_iterations: int = 3,
        runner_system_prompt: str | None = None,
        context_config: AssemblyConfig | None = None,
        min_retain_turns: int = 10,
        trace_dir: str | None = None,
        compaction_token_limit: int | None = None,
        output_trimmer: OutputTrimmer | None = None,
        roles: list[RoleConfig] | None = None,
        role_dispatcher: RoleDispatcher | None = None,
    ) -> None:
        super().__init__(
            name,
            model_client,
            system_prompt or DEFAULT_PLANNER_PROMPT,
            settings,
            context_config,
            min_retain_turns,
            trace_dir,
            compaction_token_limit,
            output_trimmer,
        )
        self.tool_registry = tool_registry
        self.max_tool_iterations = max_tool_iterations
        self.runner_system_prompt = runner_system_prompt or DEFAULT_RUNNER_PROMPT
        self.roles = roles or []
        self.role_dispatcher = role_dispatcher

    async def arespond(self, input_text: str, **kwargs: object) -> str:
        steps = await self._plan(input_text, **kwargs)
        answer = await self._run_steps(input_text, steps, **kwargs)

        self.record_message(ChatMessage(content=input_text, role="user"))
        self.record_message(ChatMessage(content=answer, role="assistant"))
        return answer

    async def _plan(self, question: str, **kwargs: object) -> list[PlanStep]:
        cancellation = kwargs.get("cancellation")
        if cancellation is not None:
            cancellation.raise_if_cancelled()

        # propose_steps 是强制 function-call、无文本可流的规划阶段，cancellation/on_text_delta/
        # on_reasoning_delta 只对后面 _run_steps 里的 run_tool_turn 调用有意义，这里要先摘掉再转发给后端。
        backend_kwargs = {
            k: v for k, v in kwargs.items() if k not in ("cancellation", "on_text_delta", "on_reasoning_delta")
        }
        prompt = f"Produce a step-by-step plan for:\n\n{question}"
        if self.roles:
            role_summary = "; ".join(f"{r.name}: {r.description}" for r in self.roles)
            prompt += (
                f"\n\nAvailable roles you may delegate individual steps to: {role_summary}. "
                "Assign a step to a role only when that role is clearly suited for it; "
                "otherwise omit the role and you will execute the step yourself."
            )
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        # tool_choice 用 "required"（必须调用某个工具，不点名）而不是指定具体函数名——
        # 后者在某些"常驻思维链"模型（如 kimi-k3）上会被 API 拒绝："tool_choice 'specified' is
        # incompatible with thinking enabled"。这里工具列表本来就只有一个，"required" 效果等价。
        completion = await self.model_client.acomplete_with_tools(
            messages,
            [_build_propose_steps_tool(self.roles)],
            tool_choice="required",
            **backend_kwargs,
        )
        if cancellation is not None:
            cancellation.record_tokens(completion.token_usage.get("total_tokens", 0))
        if not completion.requested_tools:
            steps = [PlanStep(text=question)]
        else:
            try:
                arguments = json.loads(completion.requested_tools[0].arguments_json)
            except json.JSONDecodeError:
                steps = [PlanStep(text=question)]
            else:
                raw_steps = arguments.get("steps") or [question]
                steps = [_normalize_step(s) for s in raw_steps]

        if self.recorder:
            self.recorder.log_event("plan", {"steps": [s.text for s in steps]})
        return steps

    async def _run_steps(self, question: str, steps: list[PlanStep], **kwargs: object) -> str:
        history: list[tuple[PlanStep, str]] = []
        answer = ""
        for index, step in enumerate(steps, start=1):
            context = _render_step(question, steps, history, step)
            role = self._resolve_role(step.role)
            if self.recorder:
                self.recorder.log_event(
                    "step_start", {"step_text": step.text, "role": role.name if role else None}, step=index
                )
            if role is not None and self.role_dispatcher is not None:
                try:
                    answer = await self.role_dispatcher(role.peer_url, context)
                except Exception as exc:  # noqa: BLE001 - 单步委派失败不连累其他步骤
                    answer = f"(role dispatch to '{role.name}' failed: {type(exc).__name__}: {exc})"
            else:
                messages = [
                    {"role": "system", "content": self.runner_system_prompt}, {"role": "user", "content": context}
                ]
                answer = await run_tool_turn(
                    self.model_client,
                    messages,
                    self.tool_registry,
                    self.max_tool_iterations,
                    self.recorder,
                    trimmer=self.output_trimmer,
                    on_tool_result=self.record_tool_result,
                    **kwargs,
                )
            history.append((step, answer))
        return answer

    def _resolve_role(self, role_name: str | None) -> RoleConfig | None:
        if not role_name:
            return None
        return next((r for r in self.roles if r.name == role_name), None)


def _render_step(question: str, steps: list[PlanStep], history: list[tuple[PlanStep, str]], current: PlanStep) -> str:
    plan_text = "\n".join(f"{i}. {step.text}" for i, step in enumerate(steps, start=1))
    history_text = "\n\n".join(f"Step: {step.text}\nResult: {result}" for step, result in history) or "(none yet)"
    return (
        f"# Original question\n{question}\n\n"
        f"# Full plan\n{plan_text}\n\n"
        f"# Completed steps\n{history_text}\n\n"
        f"# Current step\n{current.text}\n\n"
        "Execute the current step and give its result."
    )
