import json

from gateway.inbound_anthropic import (
    AnthropicInboundStreamAdapter,
    anthropic_request_to_chat,
    chat_response_to_anthropic,
)
from gateway.inbound_gemini import (
    GeminiInboundStreamAdapter,
    chat_response_to_gemini,
    gemini_request_to_chat,
)
from gateway.inbound_responses import (
    ResponsesStreamAdapter,
    chat_response_to_responses,
    responses_request_to_chat,
)


def test_responses_request_and_response_round_trip() -> None:
    chat = responses_request_to_chat(
        {
            "model": "openai/gpt-4o",
            "instructions": "Be concise.",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello"}],
                }
            ],
            "max_output_tokens": 100,
            "tools": [
                {
                    "type": "function",
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        }
    )
    assert chat["messages"][0] == {"role": "system", "content": "Be concise."}
    assert chat["messages"][1]["content"] == "hello"
    assert chat["tools"][0]["function"]["name"] == "read_file"
    assert chat["max_tokens"] == 100

    response = chat_response_to_responses(
        {
            "id": "chatcmpl-1",
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "world",
                        "reasoning_content": "brief",
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
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        },
        "openai/gpt-4o",
    )
    assert response["object"] == "response"
    assert response["output_text"] == "world"
    message_item = next(item for item in response["output"] if item["type"] == "message")
    assert message_item["content"][0]["text"] == "world"
    assert any(item["type"] == "function_call" for item in response["output"])
    assert response["usage"]["input_tokens"] == 3


def test_responses_stream_adapter_emits_text_and_completion() -> None:
    adapter = ResponsesStreamAdapter("openai/gpt-4o")

    deltas = adapter.feed(
        {
            "id": "chatcmpl-1",
            "choices": [
                {
                    "delta": {"content": "hello"},
                    "finish_reason": None,
                }
            ],
        }
    )
    finished = adapter.finish("stop")

    assert any(event["type"] == "response.output_text.delta" for event in deltas)
    assert any(event["type"] == "response.completed" for event in finished)


def test_anthropic_request_response_and_stream_translation() -> None:
    chat = anthropic_request_to_chat(
        {
            "model": "anthropic/claude",
            "system": "Be careful.",
            "max_tokens": 500,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "read_file",
                            "input": {"path": "README.md"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_1",
                            "content": "body",
                        },
                        {"type": "text", "text": "summarize"},
                    ],
                },
            ],
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        }
    )
    assert chat["messages"][0] == {"role": "system", "content": "Be careful."}
    assert chat["messages"][1]["tool_calls"][0]["id"] == "tool_1"
    assert chat["messages"][2]["role"] == "tool"
    assert chat["tools"][0]["function"]["name"] == "read_file"

    response = chat_response_to_anthropic(
        {
            "id": "chatcmpl-1",
            "choices": [
                {
                    "message": {
                        "content": "world",
                        "reasoning_content": "think",
                        "tool_calls": [
                            {
                                "id": "tool_1",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"README.md"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
        "anthropic/claude",
    )
    assert response["type"] == "message"
    assert response["content"][0] == {"type": "thinking", "thinking": "think"}
    assert response["content"][2]["type"] == "tool_use"
    assert response["stop_reason"] == "tool_use"

    adapter = AnthropicInboundStreamAdapter("anthropic/claude")
    start = adapter.start()
    delta = adapter.feed({"choices": [{"delta": {"content": "hello"}}]})
    finish = adapter.finish("stop")
    assert start[0][0] == "message_start"
    assert [event_name for event_name, _data in delta] == [
        "content_block_start",
        "content_block_delta",
    ]
    assert delta[1][1]["delta"]["text"] == "hello"
    assert finish[-1][0] == "message_stop"


def test_gemini_request_response_and_stream_translation() -> None:
    chat = gemini_request_to_chat(
        {
            "systemInstruction": {"parts": [{"text": "Be useful."}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "hello"},
                        {
                            "functionResponse": {
                                "name": "read_file",
                                "response": {"content": "body"},
                            }
                        },
                    ],
                }
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "read_file",
                            "description": "Read a file",
                            "parameters": {"type": "object", "properties": {}},
                        }
                    ]
                }
            ],
            "generationConfig": {"maxOutputTokens": 300, "temperature": 0.1},
        },
        "google/gemini",
    )
    assert chat["messages"][0] == {"role": "system", "content": "Be useful."}
    assert chat["messages"][1]["content"] == "hello"
    assert chat["tools"][0]["function"]["name"] == "read_file"
    assert chat["max_tokens"] == 300

    response = chat_response_to_gemini(
        {
            "choices": [
                {
                    "message": {"content": "world"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        },
        "google/gemini",
    )
    assert response["candidates"][0]["content"]["parts"][0]["text"] == "world"
    assert response["usageMetadata"]["totalTokenCount"] == 5

    adapter = GeminiInboundStreamAdapter("google/gemini")
    chunk = adapter.feed({"choices": [{"delta": {"content": "hello"}}]})
    finish = adapter.finish("stop")
    assert chunk[0]["candidates"][0]["content"]["parts"][0]["text"] == "hello"
    assert finish[0]["candidates"][0]["finishReason"] == "STOP"
