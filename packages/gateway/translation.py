"""Translate OpenAI Chat payloads to and from Anthropic Messages."""

from __future__ import annotations

import json
import time
from typing import Any


def openai_to_anthropic_request(payload: dict[str, Any], model_id: str) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    for message in payload.get("messages", []):
        role = message.get("role")
        if role == "system":
            content = message.get("content")
            if isinstance(content, str):
                system_parts.append(content)
            continue
        if role == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id", ""),
                            "content": _text_content(message.get("content")),
                        }
                    ],
                }
            )
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = message.get("content")
            if text:
                blocks.append({"type": "text", "text": _text_content(text)})
            for call in message.get("tool_calls", []):
                function = call.get("function", {})
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {"raw": function.get("arguments")}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id", ""),
                        "name": function.get("name", ""),
                        "input": arguments,
                    }
                )
            messages.append({"role": "assistant", "content": blocks or _text_content(text)})
            continue
        messages.append(
            {
                "role": "user" if role == "user" else "user",
                "content": _anthropic_content(message.get("content")),
            }
        )

    translated: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": payload.get("max_tokens") or payload.get("max_completion_tokens") or 4096,
    }
    if system_parts:
        translated["system"] = "\n\n".join(system_parts)
    for key in ("temperature", "top_p", "stream"):
        if payload.get(key) is not None:
            translated[key] = payload[key]
    if payload.get("tools"):
        translated["tools"] = [
            {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "input_schema": tool["function"].get(
                    "parameters",
                    {"type": "object", "properties": {}},
                ),
            }
            for tool in payload["tools"]
            if tool.get("type") == "function"
        ]
    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("function"):
        translated["tool_choice"] = {
            "type": "tool",
            "name": tool_choice["function"]["name"],
        }
    return translated


def anthropic_to_openai_response(
    payload: dict[str, Any],
    requested_model: str,
) -> dict[str, Any]:
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in payload.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                }
            )
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts) or None,
    }
    if thinking_parts:
        message["reasoning_content"] = "".join(thinking_parts)
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = payload.get("usage", {})
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return {
        "id": payload.get("id") or f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": _finish_reason(payload.get("stop_reason")),
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


class AnthropicStreamTranslator:
    def __init__(self, requested_model: str) -> None:
        self.requested_model = requested_model
        self.id = f"chatcmpl-{int(time.time() * 1000)}"
        self.created = int(time.time())
        self.input_tokens = 0
        self.output_tokens = 0
        self._tool_indices: dict[int, int] = {}

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = event.get("type")
        if event_type == "message_start":
            message = event.get("message", {})
            self.id = message.get("id") or self.id
            self.input_tokens = int(
                message.get("usage", {}).get("input_tokens") or self.input_tokens
            )
            return [self._chunk({"role": "assistant", "content": ""})]
        if event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                index = len(self._tool_indices)
                self._tool_indices[int(event.get("index", 0))] = index
                return [
                    self._chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "id": block.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": block.get("name", ""),
                                        "arguments": "",
                                    },
                                }
                            ]
                        }
                    )
                ]
            return []
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                return [self._chunk({"content": delta.get("text", "")})]
            if delta.get("type") == "thinking_delta":
                return [self._chunk({"reasoning_content": delta.get("thinking", "")})]
            if delta.get("type") == "input_json_delta":
                index = self._tool_indices.get(int(event.get("index", 0)), 0)
                return [
                    self._chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "function": {
                                        "arguments": delta.get("partial_json", "")
                                    },
                                }
                            ]
                        }
                    )
                ]
            return []
        if event_type == "message_delta":
            self.output_tokens = int(
                event.get("usage", {}).get("output_tokens") or self.output_tokens
            )
            chunk = self._chunk({}, finish_reason=_finish_reason(event.get("delta", {}).get("stop_reason")))
            chunk["usage"] = {
                "prompt_tokens": self.input_tokens,
                "completion_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
            }
            return [chunk]
        return []

    def _chunk(
        self,
        delta: dict[str, Any],
        *,
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.requested_model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }


def _anthropic_content(content: Any) -> Any:
    if isinstance(content, str) or content is None:
        return content or ""
    if isinstance(content, list):
        blocks = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "image_url":
                blocks.append({"type": "text", "text": "[image input]"})
        return blocks
    return str(content)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return "" if content is None else str(content)


def _finish_reason(reason: str | None) -> str:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }.get(reason or "", "stop")
