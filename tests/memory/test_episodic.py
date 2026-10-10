from memory.episodic import EpisodicMemory


class _FakeChatStore:
    """结构上满足 EpisodicMemory，不需要显式继承——验证 Protocol 是结构化类型。"""

    def append_message(self, task_id: str, kind: str, content: str) -> dict:
        return {"id": 1, "task_id": task_id, "kind": kind, "content": content}

    def list_messages(self, task_id: str) -> list[dict]:
        return []


def test_a_structurally_matching_class_satisfies_episodic_memory():
    store: EpisodicMemory = _FakeChatStore()
    assert isinstance(store, EpisodicMemory)  # @runtime_checkable：真正验证结构化类型生效
    assert store.append_message("t1", "user", "hi")["content"] == "hi"
    assert store.list_messages("t1") == []
