from memory.extraction import ExtractedMemory, build_extraction_messages, parse_extraction


def test_build_extraction_messages_carries_turn_and_no_op_first_instruction():
    messages = build_extraction_messages("我叫张三", "你好张三")

    assert messages[0]["role"] == "system"
    assert "shouldSave" in messages[0]["content"]
    assert "我叫张三" in messages[1]["content"]
    assert "你好张三" in messages[1]["content"]


def test_parse_extraction_returns_content_and_importance_when_should_save():
    text = '{"shouldSave": true, "content": "用户叫张三", "importance": 0.8}'
    assert parse_extraction(text) == ExtractedMemory(content="用户叫张三", importance=0.8)


def test_parse_extraction_defaults_importance_when_model_omits_it():
    assert parse_extraction('{"shouldSave": true, "content": "用户叫张三"}') == ExtractedMemory(
        content="用户叫张三", importance=0.5
    )


def test_parse_extraction_clamps_out_of_range_importance():
    assert parse_extraction('{"shouldSave": true, "content": "x", "importance": 1.5}').importance == 1.0
    assert parse_extraction('{"shouldSave": true, "content": "x", "importance": -0.5}').importance == 0.0


def test_parse_extraction_returns_none_for_no_save_or_bad_input():
    assert parse_extraction('{"shouldSave": false, "content": "x"}') is None
    assert parse_extraction('{"shouldSave": true, "content": "   "}') is None
    assert parse_extraction("not json") is None
    assert parse_extraction("") is None
