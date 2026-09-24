from core.compaction import summarize_history
from core.model import ModelClient
from core.protocol import ChatMessage, Completion


async def test_summarize_history_prompt_covers_code_errors_and_critical_context():
    # 摘要模板必须覆盖编程 agent 最有价值的三段，外加原有四段：出问题后能靠摘要还原
    # 涉及的文件/代码、踩过的错误和不可违反的约束。
    captured: list[list[dict]] = []
    client = ModelClient(provider="mock")

    async def fake_acomplete(messages, **kwargs):
        captured.append(messages)
        return Completion(text="summary", model_id="mock")

    client.acomplete = fake_acomplete  # type: ignore[method-assign]

    await summarize_history(client, [ChatMessage(content="hi", role="user")])

    prompt = captured[0][0]["content"]
    assert "## Goal" in prompt
    assert "## Progress" in prompt
    assert "## Decisions" in prompt
    assert "## Files and Code" in prompt
    assert "## Errors and Fixes" in prompt
    assert "## Critical Context" in prompt
    assert "## Next Steps" in prompt
