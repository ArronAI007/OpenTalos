from memory.consolidation import build_consolidation_messages, parse_consolidation


def test_build_consolidation_messages_lists_all_contents() -> None:
    messages = build_consolidation_messages(["用户叫张三", "张三是程序员"])
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "用户叫张三" in messages[1]["content"]
    assert "张三是程序员" in messages[1]["content"]


def test_parse_consolidation_returns_merged_text() -> None:
    text = '{"merged": "张三是一名程序员"}'
    assert parse_consolidation(text) == "张三是一名程序员"


def test_parse_consolidation_returns_none_for_bad_input() -> None:
    assert parse_consolidation("not json") is None
    assert parse_consolidation('{"merged": ""}') is None
    assert parse_consolidation('{"merged": "   "}') is None
    assert parse_consolidation("{}") is None
