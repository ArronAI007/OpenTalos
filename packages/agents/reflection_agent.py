from core.agent import Agent, AssemblyConfig, OutputTrimmer, RuntimeSettings
from core.agent_loop import run_tool_turn
from core.protocol import ChatMessage
from core.model import ModelClient
from tool.registry import ToolRegistry

SATISFIED_MARKER = "SATISFIED"

DEFAULT_SYSTEM_PROMPT = (
    "You are a careful assistant that drafts an answer, critiques it, and revises it. "
    f'When a critique finds nothing worth changing, respond with exactly "{SATISFIED_MARKER}".'
)


class ReflectionAgent(Agent):
    """draft -> critique -> revise 循环，critique 里出现 SATISFIED_MARKER 就提前收敛。"""

    def __init__(
        self,
        name: str,
        model_client: ModelClient,
        system_prompt: str | None = None,
        settings: RuntimeSettings | None = None,
        tool_registry: ToolRegistry | None = None,
        max_rounds: int = 3,
        max_tool_iterations: int = 3,
        context_config: AssemblyConfig | None = None,
        min_retain_turns: int = 10,
        trace_dir: str | None = None,
        compaction_token_limit: int | None = None,
        output_trimmer: OutputTrimmer | None = None,
    ) -> None:
        super().__init__(
            name,
            model_client,
            system_prompt or DEFAULT_SYSTEM_PROMPT,
            settings,
            context_config,
            min_retain_turns,
            trace_dir,
            compaction_token_limit,
            output_trimmer,
        )
        self.tool_registry = tool_registry
        self.max_rounds = max_rounds
        self.max_tool_iterations = max_tool_iterations
        self.trace: list[dict[str, str]] = []

    async def arespond(self, input_text: str, **kwargs: object) -> str:
        self.trace = []
        attempt = await self._call("draft", f"Complete the following task:\n\n{input_text}", **kwargs)
        self.trace.append({"phase": "draft", "content": attempt})

        for _ in range(self.max_rounds):
            critique = await self._call("critique", _critique_prompt(input_text, attempt), **kwargs)
            self.trace.append({"phase": "critique", "content": critique})
            if SATISFIED_MARKER in critique:
                break
            attempt = await self._call("draft", _revise_prompt(input_text, attempt, critique), **kwargs)
            self.trace.append({"phase": "draft", "content": attempt})

        self.record_message(ChatMessage(content=input_text, role="user"))
        self.record_message(ChatMessage(content=attempt, role="assistant"))
        await self.maybe_compress_history()
        return attempt

    async def _call(self, phase: str, user_text: str, **kwargs: object) -> str:
        if self.recorder:
            self.recorder.log_event("phase_start", {"phase": phase})
        messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user_text}]
        return await run_tool_turn(
            self.model_client,
            messages,
            self.tool_registry,
            self.max_tool_iterations,
            self.recorder,
            trimmer=self.output_trimmer,
            **kwargs,
        )


def _critique_prompt(task: str, attempt: str) -> str:
    return (
        f"# Task\n{task}\n\n# Current answer\n{attempt}\n\n"
        f'Critique this answer. If it needs no changes, respond with exactly "{SATISFIED_MARKER}".'
    )


def _revise_prompt(task: str, attempt: str, critique: str) -> str:
    return f"# Task\n{task}\n\n# Previous answer\n{attempt}\n\n# Critique\n{critique}\n\nProvide an improved answer."
