import asyncio
from abc import ABC, abstractmethod

from context import AssemblyConfig, ContextAssembler, ContextSlice, TokenBudget, TranscriptStore
from observability import RunRecorder

from .chat_message import ChatMessage
from .compaction import summarize_history
from .events import AgentPhase, PhaseCallback, PhaseSignal
from .model_client import ModelClient
from .settings import RuntimeSettings


class Agent(ABC):
    def __init__(
        self,
        name: str,
        model_client: ModelClient,
        system_prompt: str | None = None,
        settings: RuntimeSettings | None = None,
        context_config: AssemblyConfig | None = None,
        min_retain_turns: int = 10,
        trace_dir: str | None = None,
        compaction_token_limit: int | None = None,
    ) -> None:
        self.name = name
        self.model_client = model_client
        self.system_prompt = system_prompt
        self.settings = settings or RuntimeSettings()
        self._transcript = TranscriptStore(min_retain_turns=min_retain_turns, message_type=ChatMessage)
        self._context_assembler = ContextAssembler(context_config)
        self.recorder: RunRecorder | None = RunRecorder(output_dir=trace_dir) if trace_dir else None
        self.compaction_token_limit = compaction_token_limit
        self._tokens = TokenBudget()

    @abstractmethod
    async def arespond(self, input_text: str, **kwargs: object) -> str: ...

    async def arespond_with_callbacks(
        self,
        input_text: str,
        on_start: PhaseCallback = None,
        on_finish: PhaseCallback = None,
        on_error: PhaseCallback = None,
        **kwargs: object,
    ) -> str:
        await self._notify(AgentPhase.STARTED, on_start, input_text=input_text)
        try:
            result = await self.arespond(input_text, **kwargs)
        except Exception as error:
            await self._notify(AgentPhase.FAILED, on_error, error=str(error), error_type=type(error).__name__)
            raise
        await self._notify(AgentPhase.FINISHED, on_finish, result=result)
        return result

    async def _notify(self, phase: AgentPhase, callback: PhaseCallback, **data: object) -> None:
        if callback is None:
            return
        signal = PhaseSignal.emit(phase, self.name, **data)
        try:
            await asyncio.wait_for(callback(signal), timeout=self.settings.callback_timeout_seconds)
        except Exception:
            # 回调超时或回调自身抛异常都不应打断 Agent 主流程（设计如此）。
            pass

    def record_message(self, message: ChatMessage) -> None:
        self._transcript.append(message)

    def history_snapshot(self) -> list[ChatMessage]:
        return self._transcript.messages()

    def reset_history(self) -> None:
        self._transcript.clear()

    def compress_history(self, summary: str) -> bool:
        """把 min_retain_turns 之前的历史折叠成一条 summary 消息，回合数不足时是 no-op。"""
        return self._transcript.compress(summary)

    async def maybe_compress_history(self) -> bool:
        """历史消息的预估 token 数达到 compaction_token_limit 时，用 LLM 生成结构化摘要并折叠旧历史。

        compaction_token_limit 为 None（默认）时是 no-op，不会产生额外的模型调用；子类在每轮
        arespond() 结束时调用它即可获得自动压缩，不需要调用方手动拼摘要。
        """
        if self.compaction_token_limit is None:
            return False
        messages = self.history_snapshot()
        if self._tokens.estimate_messages(messages) < self.compaction_token_limit:
            return False
        summary = await summarize_history(self.model_client, messages)
        return self.compress_history(summary)

    def build_context(self, user_query: str, extra_slices: list[ContextSlice] | None = None) -> str:
        """跑一遍 GSSC 流水线，把 system_prompt + 历史 + user_query 组装成结构化上下文。"""
        return self._context_assembler.assemble(
            user_query,
            transcript=self.history_snapshot(),
            system_instructions=self.system_prompt,
            extra_slices=extra_slices,
        )
