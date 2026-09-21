"""対応 packages/tracing/src/index.ts。"""

from opentalos.core_types import EventHandler, TraceEvent


class InMemoryEventBus:
    def __init__(self) -> None:
        self._handlers: set[EventHandler] = set()
        self._log: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self._log.append(event)
        for handler in list(self._handlers):
            handler(event)

    def subscribe(self, handler: EventHandler):
        self._handlers.add(handler)
        return lambda: self._handlers.discard(handler)

    async def flush(self) -> None:
        pass  # 内存实现没什么好等的

    def get_events(self) -> list[TraceEvent]:
        return list(self._log)
