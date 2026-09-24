"""跟进问题推荐：解析弹性 + 静默降级的守护测试。"""
import asyncio
from typing import Any

import pytest
from core.protocol import Completion
from suggest import _parse_items, suggest_followups


def _history(*contents: str) -> list[dict[str, Any]]:
    # kind 交错（user/assistant）足以覆盖过滤与拼接逻辑；id/created_at 本模块不消费
    return [
        {"id": i + 1, "kind": "user" if i % 2 == 0 else "assistant", "content": c, "created_at": ""}
        for i, c in enumerate(contents)
    ]


class TestParseItems:
    def test_plain_json_array(self) -> None:
        assert _parse_items('["a", "b", "c"]') == ["a", "b", "c"]

    def test_array_wrapped_in_prose(self) -> None:
        text = '好的，推荐如下：\n["接着问A", "再聊聊B"]\n希望对你有帮助'
        assert _parse_items(text) == ["接着问A", "再聊聊B"]

    def test_not_json_returns_empty(self) -> None:
        assert _parse_items("这根本不是 JSON") == []

    def test_json_object_with_nested_array_extracts_the_array(self) -> None:
        # 宽松解析：模型把数组包在对象里也能截取首个 [...] 片段救回来
        assert _parse_items('{"questions": ["a"]}') == ["a"]

    def test_json_scalar_returns_empty(self) -> None:
        assert _parse_items('"just a string"') == []

    def test_filters_non_strings_and_blanks(self) -> None:
        assert _parse_items('["a", 1, null, "  ", "b"]') == ["a", "b"]

    def test_truncates_to_three(self) -> None:
        assert _parse_items('["1", "2", "3", "4", "5"]') == ["1", "2", "3"]

    def test_empty_or_all_blank_returns_empty(self) -> None:
        assert _parse_items("[]") == []
        assert _parse_items('["", "  "]') == []


class TestSuggestFollowups:
    def test_returns_items_on_success(self, scripted_client) -> None:
        client = scripted_client(completions=[
            Completion(text='["然后呢？","举个例子","有对比吗"]', model_id="mock-model"),
        ])
        items = asyncio.run(suggest_followups(client, _history("hi", "你好")))
        assert items == ["然后呢？", "举个例子", "有对比吗"]

    def test_empty_history_skips_model_call(self, scripted_client) -> None:
        client = scripted_client()  # 无 completions 队列：一旦被调用会因队列空 IndexError
        assert asyncio.run(suggest_followups(client, [])) == []
        # 只有 tool/stopped 行同样视为无对话内容
        rows = [{"id": 1, "kind": "stopped", "content": "", "created_at": ""}]
        assert asyncio.run(suggest_followups(client, rows)) == []

    def test_model_error_degrades_to_empty(self, scripted_client) -> None:
        client = scripted_client()

        async def raising(_messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
            raise RuntimeError("model down")

        client.acomplete = raising  # type: ignore[method-assign]
        assert asyncio.run(suggest_followups(client, _history("hi", "你好"))) == []

    def test_timeout_degrades_to_empty(self, scripted_client) -> None:
        client = scripted_client()

        async def slow(_messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
            await asyncio.sleep(0.3)
            return Completion(text='["x"]', model_id="mock-model")

        client.acomplete = slow  # type: ignore[method-assign]
        assert asyncio.run(suggest_followups(client, _history("hi", "你好"), timeout=0.05)) == []

    def test_prompt_uses_tail_window_and_truncates_long_rows(self, scripted_client) -> None:
        captured: list[dict[str, Any]] = []
        client = scripted_client()

        async def spy(messages: list[dict[str, Any]], **_kwargs: Any) -> Completion:
            captured.extend(messages)
            return Completion(text='["x"]', model_id="mock-model")

        client.acomplete = spy  # type: ignore[method-assign]
        long_content = "长" * 800
        history = _history("第1轮问", "第1轮答", "第2轮问", "第2轮答", "第3轮问", "第3轮答", "第4轮问", long_content)
        assert asyncio.run(suggest_followups(client, history)) == ["x"]

        user_prompt = captured[-1]["content"]
        assert "第1轮问" not in user_prompt  # 只取尾部 6 条（第2轮问起）
        assert "第2轮问" in user_prompt
        assert ("长" * 500) in user_prompt
        assert ("长" * 501) not in user_prompt  # 单行内容截断 500 字符
