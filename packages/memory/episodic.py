from typing import Protocol, runtime_checkable


@runtime_checkable
class EpisodicMemory(Protocol):
    """情景记忆的形状声明——对应现在 apps/api/db.py 的 ChatStore 已经在做的事情。这是一个
    纯类型声明，不含实现：ChatStore 的方法签名已经满足这个形状，不需要为了"实现"这个接口
    而改任何代码（PEP 544 结构化类型，不要求显式继承）。
    """

    def append_message(self, task_id: str, kind: str, content: str) -> dict: ...
    def list_messages(self, task_id: str) -> list[dict]: ...
