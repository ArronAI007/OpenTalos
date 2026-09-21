import asyncio
from abc import ABC, abstractmethod

from .chat_message import ChatMessage
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
    ) -> None:
        self.name = name
        self.model_client = model_client
        self.system_prompt = system_prompt
        self.settings = settings or RuntimeSettings()
        self._transcript: list[ChatMessage] = []

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
        return list(self._transcript)

    def reset_history(self) -> None:
        self._transcript.clear()
