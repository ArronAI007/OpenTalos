from memory.extraction import build_extraction_messages, parse_extraction


def test_build_extraction_messages_carries_turn_and_no_op_first_instruction():
    messages = build_extraction_messages("我叫张三", "你好张三")

    assert messages[0]["role"] == "system"
    assert "shouldSave" in messages[0]["content"]
    assert "我叫张三" in messages[1]["content"]
    assert "你好张三" in messages[1]["content"]


def test_parse_extraction_returns_content_when_should_save():
    assert parse_extraction('{"shouldSave": true, "content": "用户叫张三"}') == "用户叫张三"


def test_parse_extraction_returns_none_for_no_save_or_bad_input():
    assert parse_extraction('{"shouldSave": false, "content": "x"}') is None
    assert parse_extraction('{"shouldSave": true, "content": "   "}') is None
    assert parse_extraction("not json") is None
    assert parse_extraction("") is None
