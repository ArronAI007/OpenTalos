from gateway.translation import (
    AnthropicStreamTranslator,
    anthropic_to_openai_response,
    openai_to_anthropic_request,
)


def test_openai_request_translates_messages_tools_and_reasoning() -> None:
    translated = openai_to_anthropic_request(
        {
            "model": "anthropic/claude-sonnet-5",
            "messages": [
                {"role": "system", "content": "Be precise."},
                {"role": "user", "content": "Read the file."},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"README.md"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "file body",
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.2,
            "stream": True,
        },
        "claude-sonnet-5",
    )

    assert translated["model"] == "claude-sonnet-5"
    assert translated["system"] == "Be precise."
    assert translated["max_tokens"] == 1000
    assert translated["stream"] is True
    assert translated["tools"][0]["name"] == "read_file"
    assert translated["messages"][1]["content"][0]["type"] == "tool_use"
    assert translated["messages"][2]["content"][0]["type"] == "tool_result"


def test_anthropic_response_translates_text_tool_calls_and_usage() -> None:
    translated = anthropic_to_openai_response(
        {
            "id": "msg_1",
            "model": "claude-sonnet-5",
            "content": [
                {"type": "thinking", "thinking": "Need a file."},
                {"type": "text", "text": "I will read it."},
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 12, "output_tokens": 8},
        },
        "anthropic/claude-sonnet-5",
    )

    choice = translated["choices"][0]
    assert choice["message"]["content"] == "I will read it."
    assert choice["message"]["reasoning_content"] == "Need a file."
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "read_file"
    assert choice["finish_reason"] == "tool_calls"
    assert translated["usage"]["total_tokens"] == 20


def test_anthropic_stream_translator_emits_openai_chunks() -> None:
    translator = AnthropicStreamTranslator("anthropic/claude-sonnet-5")

    start = translator.feed(
        {
            "type": "message_start",
            "message": {"id": "msg_1", "usage": {"input_tokens": 4}},
        }
    )
    text = translator.feed(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "hello"},
        }
    )
    thinking = translator.feed(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "why"},
        }
    )
    tool_start = translator.feed(
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "tool_1",
                "name": "read_file",
                "input": {},
            },
        }
    )
    tool_args = translator.feed(
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        }
    )
    finish = translator.feed(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 7},
        }
    )

    assert start[0]["choices"][0]["delta"]["role"] == "assistant"
    assert text[0]["choices"][0]["delta"]["content"] == "hello"
    assert thinking[0]["choices"][0]["delta"]["reasoning_content"] == "why"
    assert tool_start[0]["choices"][0]["delta"]["tool_calls"][0]["id"] == "tool_1"
    assert tool_args[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == '{"path":'
    assert finish[0]["choices"][0]["finish_reason"] == "tool_calls"
    assert finish[0]["usage"]["total_tokens"] == 11
