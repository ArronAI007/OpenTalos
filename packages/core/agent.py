import asyncio
from abc import ABC, abstractmethod

from .config import Config
from .lifecycle import AgentEvent, EventType, LifecycleHook
from .llm import LLMClient
from .message import Message


class Agent(ABC):
    def __init__(
        self,
        name: str,
        llm: LLMClient,
        system_prompt: str | None = None,
        config: Config | None = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.config = config or Config()
        self._history: list[Message] = []

    @abstractmethod
    async def arun(self, input_text: str, **kwargs: object) -> str: ...

    async def run_with_hooks(
        self,
        input_text: str,
        on_start: LifecycleHook = None,
        on_finish: LifecycleHook = None,
        on_error: LifecycleHook = None,
        **kwargs: object,
    ) -> str:
        await self._emit_event(EventType.AGENT_START, on_start, input_text=input_text)
        try:
            result = await self.arun(input_text, **kwargs)
        except Exception as error:
            await self._emit_event(EventType.AGENT_ERROR, on_error, error=str(error), error_type=type(error).__name__)
            raise
        await self._emit_event(EventType.AGENT_FINISH, on_finish, result=result)
        return result

    async def _emit_event(self, event_type: EventType, hook: LifecycleHook, **data: object) -> None:
        if hook is None:
            return
        event = AgentEvent.create(event_type, self.name, **data)
        try:
            await asyncio.wait_for(hook(event), timeout=self.config.hook_timeout_seconds)
        except Exception:
            # 钩子超时或钩子自身抛异常都不应打断 Agent 主流程（设计如此，见 spec 第六节）。
            pass

    def add_message(self, message: Message) -> None:
        self._history.append(message)

    def get_history(self) -> list[Message]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
