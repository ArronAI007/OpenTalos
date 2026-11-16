"""Translate inbound Anthropic Messages payloads to canonical Chat payloads."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any


def anthropic_request_to_chat(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("system")
    if system:
        messages.append({"role": "system", "content": _text(system)})
    for message in payload.get("messages", []):
        role = message.get("role", "user")
        blocks = message.get("content")
        if isinstance(blocks, str):
            messages.append({"role": role, "content": blocks})
            continue
        if not isinstance(blocks, list):
            continue
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in blocks:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "thinking":
                text_parts.append(block.get("thinking", ""))
            elif block_type == "tool_use":
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
            elif block_type == "tool_result":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": _text(block.get("content")),
                    }
                )
        content = "".join(text_parts) or None
        if content is not None or tool_calls:
            translated: dict[str, Any] = {"role": role, "content": content}
            if tool_calls:
                translated["tool_calls"] = tool_calls
            messages.append(translated)
    result: dict[str, Any] = {
        "model": payload["model"],
        "messages": messages,
        "max_tokens": payload.get("max_tokens") or 4096,
        "stream": bool(payload.get("stream")),
    }
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            result[key] = payload[key]
    if payload.get("tools"):
        result["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for tool in payload["tools"]
        ]
    return result


def chat_response_to_anthropic(
    payload: dict[str, Any],
    requested_model: str,
) -> dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message", {})
    content: list[dict[str, Any]] = []
    if message.get("reasoning_content"):
        content.append({"type": "thinking", "thinking": message["reasoning_content"]})
    if message.get("content") is not None:
        content.append({"type": "text", "text": message["content"]})
    for call in message.get("tool_calls", []):
        try:
            arguments = json.loads(call.get("function", {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        content.append(
            {
                "type": "tool_use",
                "id": call.get("id", ""),
                "name": call.get("function", {}).get("name", ""),
                "input": arguments,
            }
        )
    usage = payload.get("usage", {})
    return {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": content,
        "stop_reason": _anthropic_stop_reason(choice.get("finish_reason")),
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


class AnthropicInboundStreamAdapter:
    def __init__(self, requested_model: str) -> None:
        self.requested_model = requested_model
        self.message_id = f"msg_{uuid.uuid4().hex[:12]}"
        self.started = False
        self.block_started = False
        self.input_tokens = 0
        self.output_tokens = 0

    def start(self) -> list[dict[str, Any]]:
        if self.started:
            return []
        self.started = True
        return [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": self.message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": self.requested_model,
                        "content": [],
                        "stop_reason": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )
        ]

    def feed(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events = self.start()
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        if delta.get("content"):
            if not self.block_started:
                self.block_started = True
                events.append(
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                )
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": delta["content"]},
                    },
                )
            )
        if delta.get("reasoning_content"):
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {
                            "type": "thinking_delta",
                            "thinking": delta["reasoning_content"],
                        },
                    },
                )
            )
        return events

    def finish(self, finish_reason: str | None) -> list[dict[str, Any]]:
        events = self.start()
        events.append(
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": _anthropic_stop_reason(finish_reason)},
                    "usage": {"output_tokens": self.output_tokens},
                },
            )
        )
        events.append(("message_stop", {"type": "message_stop"}))
        return events


def _anthropic_stop_reason(reason: str | None) -> str:
    return {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }.get(reason or "", "end_turn")


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            block.get("text", "")
            for block in value
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return "" if value is None else json.dumps(value, ensure_ascii=False)
