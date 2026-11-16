"""Translate OpenAI Responses API payloads to and from canonical Chat payloads."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any


def responses_request_to_chat(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    if payload.get("instructions"):
        messages.append({"role": "system", "content": payload["instructions"]})
    source_input = payload.get("input", [])
    if isinstance(source_input, str):
        messages.append({"role": "user", "content": source_input})
    else:
        for item in source_input:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": item.get("call_id") or item.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": item.get("name", ""),
                                    "arguments": item.get("arguments", "{}"),
                                },
                            }
                        ],
                    }
                )
                continue
            if item_type == "function_call_output":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.get("call_id", ""),
                        "content": _text(item.get("output")),
                    }
                )
                continue
            role = item.get("role", "user")
            messages.append({"role": role, "content": _responses_content(item.get("content"))})

    translated: dict[str, Any] = {
        "model": payload["model"],
        "messages": messages,
        "stream": bool(payload.get("stream")),
    }
    for source, target in (
        ("max_output_tokens", "max_tokens"),
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("tool_choice", "tool_choice"),
    ):
        if payload.get(source) is not None:
            translated[target] = payload[source]
    if payload.get("tools"):
        translated["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for tool in payload["tools"]
            if tool.get("type") == "function"
        ]
    return translated


def chat_request_to_responses(payload: dict[str, Any]) -> dict[str, Any]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in payload.get("messages", []):
        if message.get("role") == "system":
            instructions.append(_responses_content(message.get("content")))
            continue
        if message.get("role") == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": _responses_content(message.get("content")),
                }
            )
            continue
        input_items.append(
            {
                "role": message.get("role", "user"),
                "content": [
                    {
                        "type": "input_text" if message.get("role") != "assistant" else "output_text",
                        "text": _responses_content(message.get("content")),
                    }
                ],
            }
        )
        for call in message.get("tool_calls", []):
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call.get("id", ""),
                    "name": call.get("function", {}).get("name", ""),
                    "arguments": call.get("function", {}).get("arguments", "{}"),
                }
            )
    translated: dict[str, Any] = {
        "model": payload["model"],
        "input": input_items,
        "stream": bool(payload.get("stream")),
    }
    if instructions:
        translated["instructions"] = "\n\n".join(instructions)
    if payload.get("max_tokens") is not None:
        translated["max_output_tokens"] = payload["max_tokens"]
    for key in ("temperature", "top_p", "tool_choice"):
        if payload.get(key) is not None:
            translated[key] = payload[key]
    if payload.get("tools"):
        translated["tools"] = [
            {
                "type": "function",
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"].get("parameters", {}),
            }
            for tool in payload["tools"]
        ]
    return translated


def chat_response_to_responses(
    payload: dict[str, Any],
    requested_model: str,
) -> dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message", {})
    output: list[dict[str, Any]] = []
    text = message.get("content")
    if text is not None:
        output.append(
            {
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    if message.get("reasoning_content"):
        output.insert(
            0,
            {
                "id": f"rs_{uuid.uuid4().hex[:12]}",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": message["reasoning_content"]}],
            },
        )
    for call in message.get("tool_calls", []):
        output.append(
            {
                "id": f"fc_{call.get('id', uuid.uuid4().hex[:12])}",
                "type": "function_call",
                "status": "completed",
                "call_id": call.get("id", ""),
                "name": call.get("function", {}).get("name", ""),
                "arguments": call.get("function", {}).get("arguments", "{}"),
            }
        )
    usage = payload.get("usage", {})
    return {
        "id": f"resp_{uuid.uuid4().hex[:12]}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": requested_model,
        "output": output,
        "output_text": text or "",
        "parallel_tool_calls": True,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


def responses_response_to_chat(payload: dict[str, Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for item in payload.get("output", []):
        item_type = item.get("type")
        if item_type == "message":
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    text_parts.append(content.get("text", ""))
        elif item_type == "reasoning":
            for summary in item.get("summary", []):
                reasoning_parts.append(summary.get("text", ""))
        elif item_type == "function_call":
            tool_calls.append(
                {
                    "id": item.get("call_id") or item.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                    },
                }
            )
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts) or None,
    }
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = payload.get("usage", {})
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return {
        "id": payload.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        },
    }


class ResponsesStreamAdapter:
    def __init__(self, requested_model: str) -> None:
        self.requested_model = requested_model
        self.response_id = f"resp_{uuid.uuid4().hex[:12]}"
        self.output_item_id = f"msg_{uuid.uuid4().hex[:12]}"
        self.sequence = 0
        self.started = False
        self.text_started = False

    def start(self) -> list[dict[str, Any]]:
        if self.started:
            return []
        self.started = True
        return [
            self._event("response.created", response=self._response("in_progress")),
            self._event(
                "response.output_item.added",
                output_index=0,
                item={
                    "id": self.output_item_id,
                    "type": "message",
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                },
            ),
        ]

    def feed(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events = self.start()
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        if delta.get("content"):
            if not self.text_started:
                self.text_started = True
                events.append(
                    self._event(
                        "response.content_part.added",
                        item_id=self.output_item_id,
                        output_index=0,
                        content_index=0,
                        part={"type": "output_text", "text": "", "annotations": []},
                    )
                )
            events.append(
                self._event(
                    "response.output_text.delta",
                    item_id=self.output_item_id,
                    output_index=0,
                    content_index=0,
                    delta=delta["content"],
                )
            )
        if delta.get("reasoning_content"):
            events.append(
                self._event(
                    "response.reasoning_summary_text.delta",
                    item_id=f"rs_{self.response_id}",
                    output_index=0,
                    summary_index=0,
                    delta=delta["reasoning_content"],
                )
            )
        for call in delta.get("tool_calls", []):
            events.append(
                self._event(
                    "response.function_call_arguments.delta",
                    item_id=f"fc_{call.get('id', '')}",
                    output_index=1 + int(call.get("index", 0)),
                    delta=call.get("function", {}).get("arguments", ""),
                )
            )
        return events

    def finish(self, finish_reason: str | None) -> list[dict[str, Any]]:
        events = self.start()
        if self.text_started:
            events.append(
                self._event(
                    "response.output_text.done",
                    item_id=self.output_item_id,
                    output_index=0,
                    content_index=0,
                    text="",
                )
            )
        events.append(
            self._event(
                "response.completed",
                response=self._response("completed", finish_reason=finish_reason),
            )
        )
        return events

    def _response(self, status: str, finish_reason: str | None = None) -> dict[str, Any]:
        return {
            "id": self.response_id,
            "object": "response",
            "created_at": int(time.time()),
            "status": status,
            "model": self.requested_model,
            "output": [],
        }

    def _event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        self.sequence += 1
        return {"type": event_type, "sequence_number": self.sequence, **fields}


def _responses_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {"input_text", "output_text", "text"}
        )
    return "" if content is None else str(content)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
